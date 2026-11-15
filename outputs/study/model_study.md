# Model study

Average waiting time in seconds (lower is better), built-in simulator, the benchmark's scenarios and episode length. Written by `tools/model_study.py`.

## Model selection

The same recipe trained 5 times; only the training seed differs. Means over the validation seeds [100, 101, 102, 103, 104], which are neither training traffic nor benchmark seeds. The model with the lowest mean is the shipped one: training seed 45.

| model                          |  low | medium | high |  rush | surge | mean |
|:-------------------------------|-----:|-------:|-----:|------:|------:|-----:|
| fixed-time                     | 26.3 |   34.4 | 70.3 | 113.9 |  41.5 | 57.3 |
| max-pressure                   | 19.1 |   23.5 | 33.5 |  42.2 |  27.4 | 29.1 |
| RL, training seed 42           | 22.2 |   26.5 | 33.6 |  38.0 |  28.2 | 29.7 |
| RL, training seed 43           | 20.2 |   24.5 | 31.6 |  38.6 |  26.3 | 28.2 |
| RL, training seed 44           | 21.1 |   23.9 | 32.3 |  37.4 |  26.5 | 28.2 |
| RL, training seed 45 (shipped) | 19.0 |   23.1 | 30.3 |  36.2 |  24.7 | 26.7 |
| RL, training seed 46           | 22.4 |   22.9 | 29.4 |  36.4 |  25.2 | 27.3 |

## Training-to-training variation

The same models on the benchmark seeds [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]: what a retrain of the same recipe can give.

| model                          |       low |    medium |      high |      rush |     surge |      mean |
|:-------------------------------|----------:|----------:|----------:|----------:|----------:|----------:|
| fixed-time                     |      26.0 |      33.9 |      70.1 |     122.8 |      40.6 |      58.7 |
| max-pressure                   |      18.3 |      22.7 |      33.9 |      43.3 |      25.8 |      28.8 |
| RL, training seed 42           |      22.5 |      26.1 |      33.6 |      38.8 |      28.5 |      29.9 |
| RL, training seed 43           |      20.0 |      24.1 |      33.6 |      40.7 |      26.4 |      29.0 |
| RL, training seed 44           |      20.8 |      23.7 |      32.8 |      37.6 |      26.4 |      28.2 |
| RL, training seed 45 (shipped) |      19.0 |      22.8 |      30.9 |      36.0 |      25.1 |      26.7 |
| RL, training seed 46           |      22.7 |      22.3 |      30.7 |      36.5 |      25.1 |      27.5 |
| **RL, mean of the models**     |      21.0 |      23.8 |      32.3 |      37.9 |      26.3 |      28.3 |
| RL, lowest to highest          | 19.0–22.7 | 22.3–26.1 | 30.7–33.6 | 36.0–40.7 | 25.1–28.5 | 26.7–29.9 |
| RL, standard deviation         |       1.6 |       1.4 |       1.4 |       1.9 |       1.4 |       1.2 |
| models below max-pressure      |    0 of 5 |    1 of 5 |    5 of 5 |    5 of 5 |    2 of 5 |    3 of 5 |

## Ablation

Each row is one model trained with seed 42 and one ingredient removed, on the benchmark seeds; the line under it is its difference to the full model of the same training seed. One training run each: compare the differences with the standard deviation above before reading anything into them.

| model                                      |  low | medium | high | rush | surge | mean |
|:-------------------------------------------|-----:|-------:|-----:|-----:|------:|-----:|
| full model, training seed 42               | 22.5 |   26.1 | 33.6 | 38.8 |  28.5 | 29.9 |
| without the per-phase pressure inputs      | 24.8 |   24.3 | 33.2 | 38.2 |  28.0 | 29.7 |
|   difference                               | +2.3 |   −1.8 | −0.5 | −0.6 |  −0.5 | −0.2 |
| without the demand inputs (rate and trend) | 27.1 |   30.0 | 37.0 | 43.1 |  33.0 | 34.0 |
|   difference                               | +4.6 |   +3.9 | +3.4 | +4.3 |  +4.5 | +4.1 |
| without emergency vehicles during training | 20.6 |   25.0 | 35.0 | 39.0 |  28.0 | 29.5 |
|   difference                               | −1.9 |   −1.0 | +1.4 | +0.2 |  −0.5 | −0.4 |
