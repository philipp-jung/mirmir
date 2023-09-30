# GARF baseline

To measure a baseline with GARF, you have two options:

1) Run GARF in your terminal
2) Deploy GARF to Kubernetes

In any case, you will need to use `python 3.7` to run GARF.
In this directory, there is a `.python-version` file, which is used by `pyenv` and offers you one way to manage your python versions.

**Requirements**
GARF depends on `tensorflow < 2.0`, which is not supported anymore and generally not available for ARM chips.
You  will not be able to run GARF on an ARM system, or build the docker image on an ARM system due to that.


## 1) Run GARF In Your Terminal

To run GARF in your terminal, first create a virtual environment and activate it.
Then, install dependencies via `python -m pip install -r src/requirements.txt`.

Next, run `python export_to_garf.py`.
This will read datasets from `/mirmir/datasets/` into a sqlite3 database located at `src/database.db`.

In `src/main.py`, you can manually set the dataset name, e.g. `dataset = 'hospital'`.
To find the names of all available datasets, connect to the sqlite database and check the table names:

```
sqlite3 database.db
.tables
```

## 2) Run GARF on Kubernetes

To run GARF on Kubernetes, install Docker on your machine.
Then, [continue here]
