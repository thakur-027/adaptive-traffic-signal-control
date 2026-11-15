# Benchmark Summary

Grid: 2x2 | seeds: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | episode: 1800s | means over the seeds of outputs/benchmark_results.csv

## Average waiting time (s) by scenario and controller

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |       26.0 |         18.3 | 19.0 |
| medium   |       33.9 |         22.7 | 22.8 |
| high     |       70.1 |         33.9 | 30.9 |
| rush     |      122.8 |         43.3 | 36.0 |
| surge    |       40.6 |         25.8 | 25.1 |

## Waiting time: RL against each baseline, seed by seed

Each row compares the two controllers on the same seeds (identical traffic). *Difference* is RL minus the baseline, averaged over the seeds, with its 95 % confidence interval (Student t): negative means RL waits less, and an interval that does not reach 0 means the difference is beyond seed-to-seed noise. *RL lower in* counts the seeds where RL's waiting time was lower.

**RL vs fixed_time**

| scenario | fixed_time (s) | rl (s) | difference (s) |  change | RL lower in |
|:---------|---------------:|-------:|---------------:|--------:|------------:|
| low      |           26.0 |   19.0 |     −7.1 ± 0.6 | −27.2 % |    10 of 10 |
| medium   |           33.9 |   22.8 |    −11.0 ± 0.9 | −32.6 % |    10 of 10 |
| high     |           70.1 |   30.9 |    −39.2 ± 8.7 | −56.0 % |    10 of 10 |
| rush     |          122.8 |   36.0 |   −86.8 ± 10.6 | −70.7 % |    10 of 10 |
| surge    |           40.6 |   25.1 |    −15.5 ± 2.3 | −38.2 % |    10 of 10 |

**RL vs max_pressure**

| scenario | max_pressure (s) | rl (s) | difference (s) |  change | RL lower in |
|:---------|-----------------:|-------:|---------------:|--------:|------------:|
| low      |             18.3 |   19.0 |     +0.6 ± 0.7 |  +3.4 % |     2 of 10 |
| medium   |             22.7 |   22.8 |     +0.1 ± 0.9 |  +0.4 % |     6 of 10 |
| high     |             33.9 |   30.9 |     −3.0 ± 1.2 |  −8.9 % |    10 of 10 |
| rush     |             43.3 |   36.0 |     −7.3 ± 2.7 | −16.9 % |    10 of 10 |
| surge    |             25.8 |   25.1 |     −0.7 ± 0.9 |  −2.9 % |     7 of 10 |


## Average queue (veh/intersection)

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |        2.9 |          2.0 |  2.1 |
| medium   |        6.6 |          4.4 |  4.4 |
| high     |       20.6 |          9.9 |  9.0 |
| rush     |       40.2 |         14.1 | 11.7 |
| surge    |        7.3 |          4.6 |  4.5 |

## Throughput (vehicles completed)

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |        793 |          794 |  794 |
| medium   |       1368 |         1370 | 1371 |
| high     |       2004 |         2056 | 2060 |
| rush     |       2088 |         2276 | 2287 |
| surge    |       1287 |         1287 | 1285 |

## Emergency clearance time (s)

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |       25.4 |         25.9 | 19.5 |
| medium   |       28.9 |         26.0 | 17.3 |
| high     |       72.3 |         38.9 | 26.0 |
| rush     |      106.1 |         34.5 | 29.2 |
| surge    |       63.7 |         40.2 | 24.8 |

## RL vs fixed-time: change (%)

Negative = RL is lower. For waiting time and queue length lower is better; for throughput higher is better. Same sign convention as README.md.

| scenario | waiting time |   queue | throughput |
|:---------|-------------:|--------:|-----------:|
| low      |      −27.2 % | −27.4 % |      0.0 % |
| medium   |      −32.6 % | −32.8 % |     +0.2 % |
| high     |      −56.0 % | −56.3 % |     +2.8 % |
| rush     |      −70.7 % | −70.8 % |     +9.6 % |
| surge    |      −38.2 % | −38.3 % |     −0.1 % |
| **mean** |      −44.9 % | −45.1 % |     +2.5 % |
