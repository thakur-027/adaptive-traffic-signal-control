# How it works, in plain language

A walkthrough of the project for a reader who knows some Python but not reinforcement
learning or traffic engineering. Each section names the file that implements what it
describes. Results are not repeated here: the headline tables are in [README.md](README.md)
and every table is in [REPORT.md](REPORT.md) §6.

---

## 1. The idea in one paragraph

Most traffic lights run on fixed timers: each direction gets the same green every cycle,
however many vehicles are waiting. This project replaces the timer with learning agents, one
per junction of a 2 × 2 grid. Every five seconds each agent looks at its own queues, at what
its neighbours are doing and at how fast traffic is arriving, and asks for the phase it
thinks is best. A separate safety layer, which the agents cannot bypass, turns that request
into lamp changes with the mandatory amber and all-red. The agents learn by trial and error
in a simulator, rewarded for short waits. The result is compared with a fixed timer and with
max-pressure, a strong hand-written adaptive rule, on identical traffic.

---

## 2. Why this is a learning problem

A fixed-time signal is a metronome. Real traffic is lopsided (a main road carries far more
than a side street) and changes over the day, so a metronome leaves vehicles waiting at a red
light while nobody crosses.

Controlling a signal is a **sequence of decisions under uncertainty**. Holding a green now
changes the queues you face in thirty seconds; vehicles keep arriving at random; every change
of phase costs five seconds in which nobody moves. Reinforcement learning is built for this:
an **agent** learns a **policy**, a rule from situation to action, that maximises reward over
the long run rather than at the next step.

A hand-written rule can also be adaptive. Max-pressure serves whichever phase has the larger
queue imbalance and is provably good at keeping throughput up. It is the honest yardstick,
and the results are stated against it as well as against the timer.

---

## 3. How the pieces fit

```
 config.yaml ──► simulator ──► observation (33 numbers per junction)
                    ▲                     │
                    │                     ▼
              lamp state            agent (one per junction, shared weights)
                    ▲                     │  "I want phase EW"
                    │                     ▼
               safety state machine ◄── request
               (min/max green, amber, all-red)
```

One loop, repeated every 5 simulated seconds:

1. The simulator (`sim/`) moves vehicles for five seconds.
2. `envs/spaces.py` builds one observation per junction.
3. Each agent (`agents/`) outputs the phase it wants.
4. The safety state machine (`envs/phases.py`) decides what the lamps actually do.
5. While training, the reward (`envs/traffic_env.py`) tells the agents how that went.

`config.yaml` is the only place numbers live. Every module reads it.

---

## 4. What an agent sees, does and is paid for

### What it sees: 33 numbers (`envs/spaces.py`)

| Values | What | Why |
|---:|---|---|
| 4 | queue length on each approach (N, E, S, W) | where the vehicles are |
| 4 | accumulated waiting time on each approach | how long they have waited |
| 2 | which phase is green now | what it is currently doing |
| 1 | how long that green has lasted | how close it is to the limits |
| 4 | emergency flag per approach: 1 if an emergency vehicle waits there, 0.5 if one is on its way there | lets it make way before the vehicle arrives |
| 4 | each neighbour's pressure | what is about to be sent its way |
| 4 | each neighbour's current phase | lets neighbours line their greens up |
| 2 | the pressure of each of its own phases | exactly what the max-pressure rule compares |
| 4 | arrival rate on each approach (last ≈30 s) | how fast the approach is filling |
| 4 | arrival trend on each approach (30 s rate minus 120 s rate) | whether demand is building or easing |

Everything is scaled to roughly 0–1. The last ten values can be switched off in
`config.yaml` (`rl.pressure_obs`, `rl.demand_obs`); a model only works with the switches it
was trained with, and loading it under different ones stops with a message that says so.

### What it does: choose a phase (`envs/phases.py`)

The action is "which phase should be green next": north–south or east–west. It is a
*request*. The agent never writes to the lamps.

### What it is paid for (`envs/traffic_env.py`, `_rewards`)

After every decision each agent gets a number:

```
reward = − delay at my junction            (vehicle-seconds waited, scaled)
         − pressure at my junction         (queues not yet served, scaled)
         − 0.2 if I started a phase change (changing is not free)
         + 10 for every emergency vehicle that got through my junction
         − 6 for every emergency vehicle I kept waiting
```

The weights are in `config.yaml → reward`. The agent is never told *how* to shorten waits;
it finds out which requests lead to higher reward.

---

## 5. How it learns

The method is a **Double + Dueling Deep Q-Network with prioritized replay**. In order:

**Q-values.** `Q(s, a)` is an estimate of the total future reward if you take action `a` in
situation `s` and act well afterwards. If you knew Q, the policy would be trivial: pick the
action with the larger Q.

**Deep Q-Network.** There are far too many situations to store Q in a table, so a small
neural network estimates it: 33 inputs, two hidden layers of 128 units, 2 outputs — 21,251
parameters (`agents/net.py`).

**Learning from replay.** Every decision is stored as (situation, action, reward, next
situation) in a buffer of 50,000. The network is trained on batches of 64 drawn from it,
nudging `Q(s, a)` towards `reward + 0.99 × best Q of the next situation`
(`agents/double_dqn_agent.py`).

**Double DQN.** Using one network both to pick and to score the best next action makes the
estimates drift upwards. Double DQN lets the live network pick and a frozen copy (the
**target network**, refreshed every 500 updates) score.

**Dueling head.** The network splits into "how good is this situation" and "how much better
is each action than average", then recombines them. In traffic the situation often matters
more than the choice, and this lets the network learn that directly.

**Prioritized replay.** Transitions the network predicted badly are replayed more often,
with a correction so that this does not bias the result (`agents/replay.py`).

**Exploration.** At first the agent acts at random; the share of random actions falls from
100 % to 5 % over 70,000 decisions (`agents/policies.py`).

**Two interchangeable networks.** The same network exists in PyTorch and in plain NumPy with
hand-written back-propagation. They share one checkpoint format, so a model trained with one
runs on the other; the hosted site runs without PyTorch.

---

## 6. Training (`train/trainer.py`)

`python run.py train --overwrite` runs 400 episodes of 20 simulated minutes, about eight
minutes on one CPU core.

* **Curriculum.** Episodes cycle through light, medium, heavy, rush-hour and surge traffic, so
  one policy handles all of them.
* **Emergency vehicles are part of it.** On average every five minutes of an episode an
  ambulance, police car or fire engine is sent in, with no rule helping it. Getting it
  through is left to the agents and to the two emergency terms of the reward.
* **The time limit is not an ending.** An episode stops because time is up, not because the
  traffic ended, so the last step is learned from like any other.
* **Keeping the best.** Every 10 episodes the policy is tested, without random actions, on
  every scenario of the curriculum, and the best version so far is saved.

**Which model is shipped.** Training has randomness, and two runs of the same recipe do not
give the same model. The recipe was therefore run five times (`models/seeds/`). The five
models were compared on traffic none of them had seen and that the benchmark does not use
(validation seeds 100–104), and the best one there is the shipped model.
`python tools/model_study.py` reproduces that comparison and shows how far apart the five
are.

---

## 7. Four agents, one policy (`agents/multi_agent.py`)

Each junction decides for itself. There is no central controller and no messages between
agents: a junction simply *sees* its neighbours' pressure and phase among its inputs, which
is enough for neighbouring junctions to line their greens up along the main road.

All four agents share one network and one replay buffer. The junctions are alike, so what
one learns applies to the others, and four junctions produce four times the experience for
the same network. A fully joint controller would have to choose among every combination of
phases across the grid, which grows exponentially with the number of junctions; independent
agents with neighbour inputs scale to any grid.

A centralised-training variant (QMIX, `agents/qmix.py`) is implemented and switched off by
default.

---

## 8. The safety layer (`envs/phases.py`)

Whatever the agents ask for, a small state machine owns the lamps:

* a green lasts at least 10 s and at most 60 s;
* every change goes green → 3 s amber → 2 s all-red → green;
* a change that has begun always completes — a request made during the amber or all-red is
  acted on from the next green;
* so no direction waits more than 70 s for its green.

During amber and all-red no approach has green, so two crossing directions can never be green
together. This is a property of the machine, not something the agents learn, and
`tests/test_phases_safety.py` checks it over 18,000 random requests, along with the exact
durations.

The point of the separation: the learned part may be imperfect or exploring; the safe part is
simple enough to verify. Every controller in the project — the timer, max-pressure and the
agents — drives the same machine and pays the same clearance times.

---

## 9. Emergency vehicles (`control/emergency.py`, `tools/emergency_eval.py`)

Two mechanisms work together.

**Learned.** Because emergency vehicles appear during training, the agents have learned to
react to the emergency flags: on the main road they open the way for an ambulance by
themselves.

**Guaranteed.** On top of the policy sits a rule, as real preemption systems have. For the
agents' grid it clears a *green corridor*: from the moment the vehicle is sent, every
junction still ahead of it requests the phase that serves it. The fixed-time grid uses
*stop-line* preemption: a junction switches once the vehicle is waiting at it, as a
stand-alone signal would. Both go through the safety layer; amber and all-red are never
skipped.

`tools/emergency_eval.py` measures each vehicle type over 1,250 matched dispatches, with the
rule and without it, so that what the agents learned and what the rule adds can be told
apart. The short version: the agents alone handle the main road well, and the side street
(where the police car drives) needs the rule. The numbers and the caveats are in
REPORT.md §6.3 and §8.

---

## 10. How the comparison is made fair (`eval/benchmark.py`)

* **Identical traffic.** The same scenario and seed produce the same vehicles at the same
  seconds for every controller, so any difference is the controller's.
* **Two baselines.** *Fixed-time* (`control/fixed_time.py`): 30 s per direction, a sensible
  plan with the same clearances. *Max-pressure* (`control/max_pressure.py`): at every decision
  it serves the phase whose queues exceed the queues downstream by the most.
* **Ten seeds and intervals.** Each controller runs each of the five scenarios on ten seeds.
  Controllers are compared seed by seed, and each difference is reported with a 95 %
  confidence interval: if the interval includes zero, the difference is within the noise and
  is called a tie.
* **More than one model.** Five trained models, not one, so that "the method works" is not
  confused with "this checkpoint was lucky".
* **Reproducible.** `python run.py eval` regenerates every published number from the shipped
  model, byte for byte; the automated checks on GitHub fail if a number changes.

The five scenarios: light, medium, heavy and rush-hour traffic at a steady rate, and a
**surge** in which demand rises from light to rush-hour level and falls back within one
episode.

---

## 11. Two simulators (`sim/`)

* **Built-in** (`sim/mini_backend.py`): a point-queue model. Vehicles arrive at random, wait
  in a queue per approach, cross at up to one vehicle every two seconds on green and take the
  free-flow time to reach the next junction. It is fast, has no dependencies, and every
  headline number comes from it. It has no car-following, lane changing or spill-back.
* **SUMO** (`sim/sumo_backend.py`): the standard open-source microscopic simulator, used when
  installed. The same benchmark runs on it (`python run.py eval --backend sumo`), with the
  model that was trained on the built-in simulator.

Both sit behind one interface (`sim/backend.py`), so the environment, the controllers and
the benchmark do not know which one is running.

---

## 12. The dashboard (`dashboard/`)

One page shows the same four junctions twice, fed the same vehicles: the agents on the left,
the timer on the right. A server process advances both simulations and sends the browser a
compact update five times a second over a WebSocket (`session.py`, `server.py`); the browser
draws the roads, vehicles and lamps on a canvas and reconstructs the motion between updates
(`static/js/`). There is no framework and nothing is loaded from another site.

An emergency vehicle sent from the page enters both grids and is followed on both: circled
on the map, described in a line above each map, and compared in a tracker under them. Those
facts come from the simulator, not from the picture, and tests check the page's account
against the simulator frame by frame.

If FastAPI is not installed, a standard-library server serves the same page by polling.

---

## 13. Built to run anywhere

| Part | Preferred | Fallback when it is missing |
|---|---|---|
| Neural network | PyTorch | the NumPy network, same checkpoint |
| Simulator | SUMO | the built-in simulator |
| Web server | FastAPI + WebSocket | standard-library server, polling |

Each is chosen automatically. `python run.py doctor` prints what was found and what was
substituted.

---

## 14. Where things are

```
run.py                 one entry point: demo | train | eval | sim | doctor
config.yaml            every setting
src/atsc/
  sim/                 backend.py (interface, topology, metrics) · mini_backend.py ·
                       sumo_backend.py · netgen.py · sumo_detect.py
  envs/                traffic_env.py (environment, reward) · phases.py (safety) ·
                       spaces.py (observation)
  agents/              net.py · double_dqn_agent.py · multi_agent.py · replay.py ·
                       policies.py · qmix.py
  control/             fixed_time.py · max_pressure.py · rl_controller.py · emergency.py
  train/               trainer.py
  eval/                benchmark.py · metrics.py · plots.py
  dashboard/           session.py · server.py · stdlib_server.py · static/
  vehicles.py          the vehicle types drawn on the page and the emergency types
tools/                 emergency_eval.py · model_study.py · make_results_svg.py ·
                       e2e_browser.py · bench_server.py · record_gif.py
tests/                 the test suite
models/                pretrained/ (shipped) · seeds/ · ablation/
outputs/               every published CSV, table and plot
```

---

## 15. Glossary

- **Agent** — the decision-maker at one junction: a neural network plus the rule "pick the
  action with the higher Q".
- **Environment** — the simulated world the agents act in (`MultiAgentTrafficEnv`).
- **Observation / state** — the 33 numbers an agent sees at each decision.
- **Action** — the phase the agent asks for.
- **Policy** — the rule from observation to action.
- **Reward** — the score the agent tries to maximise over time.
- **Q-value** — expected total future reward of an action in a situation.
- **DQN** — a neural network that estimates Q-values.
- **Double DQN** — one network chooses the next action, another scores it, to avoid
  over-estimating.
- **Dueling network** — estimates the value of the situation and the advantage of each action
  separately.
- **Prioritized replay** — learning more often from the experiences that were predicted
  worst.
- **Target network** — a periodically refreshed copy of the network that provides stable
  learning targets.
- **Epsilon-greedy** — act at random with probability ε, otherwise greedily; ε shrinks during
  training.
- **Discount factor (γ)** — how much future reward counts against immediate reward (0.99
  here).
- **Phase** — the movements that have green together (north–south or east–west here).
- **Pressure** — the queue on an approach minus the queue it feeds downstream.
- **Max-pressure** — the rule that serves the phase with the highest pressure.
- **Preemption** — overriding the normal controller for an emergency vehicle.
- **Green corridor** — preempting every junction ahead of an emergency vehicle at once.
- **Saturation** — demand close to what a junction can discharge; queues then grow without
  limit.
- **Seed** — the number that fixes the random traffic, so a run can be repeated exactly.
- **Confidence interval** — the range in which the true average difference plausibly lies;
  if it includes zero, the difference is not established.
- **Ablation** — retraining with one ingredient removed to see what it contributed.
- **Point-queue model** — a traffic model that tracks a queue per approach instead of
  individual vehicle movements.
- **SUMO** — Simulation of Urban MObility, the standard microscopic traffic simulator.
- **MARL** — multi-agent reinforcement learning.
