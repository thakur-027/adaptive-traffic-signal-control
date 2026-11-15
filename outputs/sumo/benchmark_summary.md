# Benchmark Summary

Grid: 2x2 | seeds: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] | episode: 1800s | means over the seeds of outputs/sumo/benchmark_results.csv

## Average waiting time (s) by scenario and controller

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |       21.1 |         14.5 | 11.7 |
| medium   |       26.4 |         25.4 | 15.1 |
| high     |       45.3 |         37.9 | 22.1 |
| rush     |       53.9 |         43.1 | 25.5 |
| surge    |       30.5 |         27.6 | 16.8 |

## Waiting time: RL against each baseline, seed by seed

Each row compares the two controllers on the same seeds (identical traffic). *Difference* is RL minus the baseline, averaged over the seeds, with its 95 % confidence interval (Student t): negative means RL waits less, and an interval that does not reach 0 means the difference is beyond seed-to-seed noise. *RL lower in* counts the seeds where RL's waiting time was lower.

**RL vs fixed_time**

| scenario | fixed_time (s) | rl (s) | difference (s) |  change | RL lower in |
|:---------|---------------:|-------:|---------------:|--------:|------------:|
| low      |           21.1 |   11.7 |     −9.4 ± 0.8 | −44.5 % |    10 of 10 |
| medium   |           26.4 |   15.1 |    −11.3 ± 0.6 | −42.9 % |    10 of 10 |
| high     |           45.3 |   22.1 |    −23.2 ± 2.1 | −51.2 % |    10 of 10 |
| rush     |           53.9 |   25.5 |    −28.4 ± 1.5 | −52.6 % |    10 of 10 |
| surge    |           30.5 |   16.8 |    −13.7 ± 1.5 | −44.9 % |    10 of 10 |

**RL vs max_pressure**

| scenario | max_pressure (s) | rl (s) | difference (s) |  change | RL lower in |
|:---------|-----------------:|-------:|---------------:|--------:|------------:|
| low      |             14.5 |   11.7 |     −2.8 ± 0.9 | −19.6 % |    10 of 10 |
| medium   |             25.4 |   15.1 |    −10.3 ± 2.3 | −40.5 % |    10 of 10 |
| high     |             37.9 |   22.1 |    −15.8 ± 1.4 | −41.7 % |    10 of 10 |
| rush     |             43.1 |   25.5 |    −17.6 ± 1.4 | −40.8 % |    10 of 10 |
| surge    |             27.6 |   16.8 |    −10.8 ± 1.0 | −39.2 % |    10 of 10 |


## Average queue (veh/intersection)

| scenario | fixed_time | max_pressure |  rl |
|:---------|-----------:|-------------:|----:|
| low      |        2.3 |          1.6 | 1.3 |
| medium   |        5.0 |          4.9 | 2.9 |
| high     |       13.0 |         10.9 | 6.4 |
| rush     |       16.6 |         13.6 | 8.2 |
| surge    |        5.4 |          4.9 | 3.0 |

## Throughput (vehicles completed)

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |        781 |          783 |  785 |
| medium   |       1336 |         1327 | 1344 |
| high     |       1949 |         1949 | 2012 |
| rush     |       2062 |         2113 | 2233 |
| surge    |       1262 |         1264 | 1265 |

## Emergency clearance time (s)

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |       61.1 |         52.9 | 52.0 |
| medium   |       68.0 |         61.7 | 56.5 |
| high     |       85.8 |         85.6 | 58.9 |
| rush     |      105.0 |         98.1 | 63.7 |
| surge    |       84.8 |         86.3 | 52.5 |

## RL vs fixed-time: change (%)

Negative = RL is lower. For waiting time and queue length lower is better; for throughput higher is better. Same sign convention as README.md.

| scenario | waiting time |   queue | throughput |
|:---------|-------------:|--------:|-----------:|
| low      |      −44.5 % | −44.6 % |     +0.5 % |
| medium   |      −42.9 % | −42.9 % |     +0.5 % |
| high     |      −51.2 % | −51.0 % |     +3.3 % |
| rush     |      −52.6 % | −50.4 % |     +8.3 % |
| surge    |      −44.9 % | −45.0 % |     +0.2 % |
| **mean** |      −47.2 % | −46.8 % |     +2.6 % |
