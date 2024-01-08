# Mimir: A Holistic Value Imputation System
Mimir is a state-of-the-art error correction system.

![Boxplot comparing Mimir to Baran, another state-of-the-art error correction system.](./notebook/img/2023-12-21-mirmir-vs-baran.pdf)

## Installation
Mimir can be executed on any platform using `conda` or `mamba`.
To install Mimir on your machine, follow these steps:

1) Install Miniforge3 on you machine.\
Follow the [official installation instructions](https://github.com/conda-forge/miniforge#download).
1) Clone this repository via `git clone https://github.com/philipp-jung/mirmir.git`.
1) In the folder into which you cloned the repository, run `conda env create -n mirmir -f environment.yml` to create a new conda environment called `mirmir`.

## How to use it
Follow these instructions to clean data with `mirmir`:

1) Run `conda activate mirmir` to activate the `mirmir` environment.
1) Navigate into the `src/` folder in the directory into which you cloned `mirmir`.
1) Run `python correction.py` to correct sample data errors. Set parameters at the bottom of `correction.py` to adjust the correction process.

## Experiments
To run our experiments, consider the `README.md` file in the the `infrastructure/` directory.
