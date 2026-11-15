"""Training loop: curriculum multi-agent DQN with CSV (+ optional TensorBoard) logging.

Runs episodes across the density curriculum, stores transitions in prioritized replay,
updates the Double+Dueling DQN each step, periodically evaluates greedily, and checkpoints
the best model. Deterministic per-episode seeds make a run repeatable on one machine and
library stack; a different NumPy / PyTorch build gives a different model (README,
"Reproducibility").

Emergency vehicles are part of training: ``train.emergency_gap_s`` is the mean time between
dispatches of a randomly chosen type, and no rule-based preemption is attached, so serving
them is left to the agents (the reward's emergency terms and the emergency flags of the
observation). An episode ends at its time limit, which is not an ending of the traffic, so
the last transition is stored as non-terminal and bootstraps like every other.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

import numpy as np

from atsc.agents import build_learner
from atsc.config import project_root
from atsc.control.rl_controller import default_checkpoint_path
from atsc import vehicles
from atsc.envs.spaces import cfg_obs_size
from atsc.envs.traffic_env import MultiAgentTrafficEnv
from atsc.logging_utils import get_logger
from atsc.seeding import derive_seed, make_rng, seed_everything

log = get_logger("atsc.train")


class Trainer:
    def __init__(self, cfg, quick: bool = False, device: str = "cpu") -> None:
        self.cfg = cfg
        self.quick = quick
        self.device = device
        self.n_episodes = int(cfg.train.quick_episodes if quick else cfg.train.episodes)
        self.curriculum = list(cfg.train.curriculum)
        self.episode_seconds = int(cfg.train.episode_seconds)

        # env used for training (override episode length to the shorter training horizon)
        self.env = MultiAgentTrafficEnv(cfg, backend_name="mini")
        self.env._episode_seconds = self.episode_seconds

        self.obs_dim = cfg_obs_size(cfg)
        self.emergency_gap_s = float(cfg.train.get("emergency_gap_s", 0) or 0)
        self.emergency_types = [(e["kind"], e["corridor"]) for e in vehicles.emergency_types(cfg)]
        self.learner = build_learner(cfg, list(self.env.possible_agents),
                                     self.obs_dim, cfg.n_phases, device=device)

        self.log_dir = project_root() / cfg.train.log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # Full training writes the shipped checkpoint; --quick writes a separate file so a
        # fast demo-time train never clobbers the curated pre-trained model.
        base = default_checkpoint_path(cfg)
        self.ckpt_path = (base.with_name(base.stem + "_quick.pt") if quick else base)
        self.ckpt_path.parent.mkdir(parents=True, exist_ok=True)

        self._writer = None
        if bool(cfg.train.tensorboard):
            try:
                from torch.utils.tensorboard import SummaryWriter
                self._writer = SummaryWriter(log_dir=str(self.log_dir / "tb"))
            except Exception as exc:  # pragma: no cover
                log.warning("TensorBoard unavailable (%s); CSV logging only.", exc)

    # ------------------------------------------------------------------ #
    def train(self) -> Path:
        cfg = self.cfg
        seed_everything(cfg.seed)
        csv_path = self.log_dir / ("train_quick.csv" if self.quick else "train.csv")
        csv_file = open(csv_path, "w", newline="")
        writer = csv.writer(csv_file)
        writer.writerow(["episode", "scenario", "steps", "ep_reward", "avg_wait",
                         "avg_queue", "throughput", "epsilon", "loss", "seconds"])

        best_score = float("inf")
        log.info("Starting %s training: %d episodes on %s grid (device=%s)",
                 "QUICK" if self.quick else "FULL", self.n_episodes,
                 f"{cfg.network.grid_rows}x{cfg.network.grid_cols}", self.device)

        for ep in range(self.n_episodes):
            scenario = self.curriculum[ep % len(self.curriculum)]
            seed = derive_seed(cfg.seed, "train", scenario, ep)
            t0 = time.time()
            ep_reward, steps, loss = self._run_episode(scenario, seed)
            metrics = self.env.metrics()
            dt = time.time() - t0

            writer.writerow([ep, scenario, steps, round(ep_reward, 1),
                             round(metrics["avg_waiting_time"], 2),
                             round(metrics["avg_queue"], 2),
                             int(metrics["throughput"]),
                             round(self.learner.epsilon, 3),
                             round(loss or 0.0, 4), round(dt, 1)])
            csv_file.flush()
            if self._writer:
                self._writer.add_scalar("train/avg_wait", metrics["avg_waiting_time"], ep)
                self._writer.add_scalar("train/ep_reward", ep_reward, ep)
                self._writer.add_scalar("train/epsilon", self.learner.epsilon, ep)

            log.info("ep %2d/%d | %-6s | wait=%5.1fs q=%4.1f thru=%4d | eps=%.2f "
                     "loss=%.3f | %.1fs",
                     ep + 1, self.n_episodes, scenario, metrics["avg_waiting_time"],
                     metrics["avg_queue"], int(metrics["throughput"]),
                     self.learner.epsilon, loss or 0.0, dt)

            # periodic greedy checkpoint on a fixed eval scenario
            if (ep + 1) % int(cfg.train.eval_every) == 0 or ep == self.n_episodes - 1:
                score = self._greedy_eval_all(derive_seed(cfg.seed, "eval", ep))
                log.info("   greedy eval (mean over scenarios): avg_wait=%.1fs", score)
                if score < best_score:
                    best_score = score
                    self._save(best=True, note=f"ep{ep+1}_wait{score:.1f}")
                    log.info("   ** new best (%.1fs) -> saved checkpoint", score)

        # The best-by-greedy-eval checkpoint is the shipped model (already at ckpt_path).
        # Also keep the final-weights model alongside it for reference / resuming.
        final_path = self.ckpt_path.with_name(self.ckpt_path.stem + "_final.pt")
        self.learner.save(str(final_path), metadata={"note": "final_weights"})
        csv_file.close()
        if self._writer:
            self._writer.close()
        log.info("Training complete. Best greedy avg_wait=%.1fs. Checkpoint: %s",
                 best_score, self.ckpt_path)
        return self.ckpt_path

    # ------------------------------------------------------------------ #
    def _run_episode(self, scenario: str, seed: int):
        env = self.env
        obs = env.reset(scenario=scenario, seed=seed)
        emg_rng = make_rng(seed, "train-emergency")      # its own stream: traffic is unchanged
        p_dispatch = (float(cfg_interval(self.cfg)) / self.emergency_gap_s
                      if self.emergency_gap_s > 0 and self.emergency_types else 0.0)
        ep_reward = 0.0
        steps = 0
        last_loss = None
        not_terminal = {a: False for a in env.possible_agents}     # a time limit is no ending
        while env.agents:
            if p_dispatch and emg_rng.random() < p_dispatch \
                    and env.backend.active_emergencies() < 2:
                kind, corridor = self.emergency_types[int(emg_rng.integers(len(self.emergency_types)))]
                env.inject_emergency(corridor, kind=kind)
            actions = self.learner.act(obs, explore=True)
            next_obs, rewards, terminated, truncated, infos = env.step(actions)
            self.learner.observe(obs, actions, rewards, next_obs, not_terminal)
            loss = self.learner.learn()
            if loss is not None:
                last_loss = loss
            obs = next_obs
            ep_reward += float(sum(rewards.values()))
            steps += 1
        return ep_reward, steps, last_loss

    def _greedy_eval(self, scenario: str, seed: int) -> float:
        """Run one greedy (no-exploration) episode and return avg waiting time."""
        eval_env = MultiAgentTrafficEnv(self.cfg, backend_name="mini")
        eval_env._episode_seconds = self.episode_seconds
        obs = eval_env.reset(scenario=scenario, seed=seed)
        while eval_env.agents:
            actions = self.learner.greedy(obs)
            obs, _, _, _, _ = eval_env.step(actions)
        score = eval_env.metrics()["avg_waiting_time"]
        eval_env.close()
        return score

    def _greedy_eval_all(self, seed: int) -> float:
        """Greedy avg-waiting-time for model selection: the mean over every scenario of the
        curriculum, ``train.eval_seeds`` episodes each. The seeds are the same at every
        evaluation, so two checkpoints are compared on identical traffic, and they are
        derived from the training seed, so they are not the benchmark's.
        """
        n = max(1, int(self.cfg.train.get("eval_seeds", 1)))
        scores = [self._greedy_eval(scen, derive_seed(self.cfg.seed, "select", scen, k))
                  for scen in self.curriculum for k in range(n)]
        return float(np.mean(scores))

    def _save(self, best: bool, note: str = "") -> None:
        metadata = {
            "grid": f"{self.cfg.network.grid_rows}x{self.cfg.network.grid_cols}",
            "phase_scheme": self.cfg.network.phase_scheme,
            "obs_dim": self.obs_dim,
            "n_actions": self.cfg.n_phases,
            "neighbor_obs": bool(self.cfg.rl.neighbor_obs),
            "pressure_obs": bool(self.cfg.get_path("rl.pressure_obs", False)),
            "demand_obs": bool(self.cfg.get_path("rl.demand_obs", False)),
            "emergency_lookahead": bool(self.cfg.get_path("rl.emergency_lookahead", False)),
            "seed": int(self.cfg.seed),
            "share_parameters": bool(self.cfg.rl.share_parameters),
            "algo": "qmix" if bool(self.cfg.get_path("qmix.enabled", False))
                    else "double_dueling_dqn",
            "curriculum": self.curriculum,
            "note": note,
        }
        self.learner.save(str(self.ckpt_path), metadata=metadata)


def cfg_interval(cfg) -> int:
    return int(cfg.signal.decision_interval_s)


def train_main(cfg, quick: bool = False, device: str = "cpu") -> Path:
    return Trainer(cfg, quick=quick, device=device).train()
