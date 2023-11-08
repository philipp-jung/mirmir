import json
import itertools
import random
from pathlib import Path

def combine_configs(ranges: dict, config: dict, runs: int):
    """
    Calculate all possible configurations from combining ranges with the
    static config.
    ranges: dict of lists, where the key identifier the config-parameter,
    and the list contains possible values for that parameter.
    config: dict containing all parameters needed to run Mirmir. Keys
    contained in ranges get overwritten.
    runs: integer indicating how often a measurement should be repeated with
    one combination.
    @return: list of config-dicts
    """
    config_combinations = []
    ranges = {**ranges, "run": list(range(runs))}

    range_combinations = itertools.product(*list(ranges.values()))
    for c in range_combinations:
        combination = {}
        for i, key_range in enumerate(ranges.keys()):
            combination[key_range] = c[i]
        config_combinations.append(combination)

    configs = [
        {**config, **range_config} for range_config in config_combinations
    ]

    return configs

def generat_job(config: dict, experiment_name: str, jobs_path: Path):
    """
    Generates a kubernetes job config to run a mirmir experiment.
    """

    template = """apiVersion: batch/v1
kind: Job 
metadata:
  name: {}
spec:
  completions: 1
  template:
    metadata:
      labels:
        app: {}
    spec:
      restartPolicy: Never
      tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
      containers:
        - name: mirmir
          image: docker.io/larmor27/mirmir:latest
          env:
            - name: CONFIG
              value: '{}'
            - name: EXPERIMENT_ID
              value: {}
          volumeMounts:
            - name: mirmir-results-volume
              mountPath: /measurements  # Mounting the PVC at /app/output directory in the container
          resources:
            requests:
              # only start on nodes with 64Gi of RAM available 
              memory: "64Gi"   
              # only start on nodes with 26 CPU cores available
              cpu: 26   
            limits:
              # kill the pod when it uses more than 64Gi of RAM
              memory: "64Gi"  
              # restrict the pod to never use more than 26 full CPU cores
              cpu: 26
      volumes:
        - name: mirmir-results-volume
          persistentVolumeClaim:
            claimName: mirmir-results-volume
    """

    unique_id = f'{experiment_name}-{random.choice(range(1000000, 9999999))}'
    unique_id = unique_id.replace('_', '-')
    job_config = template.format(unique_id, unique_id, json.dumps(config), unique_id)
    with open(jobs_path / f'{unique_id}.yml', 'wt') as f:
        f.write(job_config)

def main():
    experiment_name = "2023-11-03-llm-correction-only"

    baran_configs = combine_configs(
        ranges={
        "dataset": ["beers", "flights", "hospital", "rayyan"],
        },
        config={
        "dataset": "1481",
        "error_class": "simple_mcar",
        "error_fraction": 1,
        "labeling_budget": 20,
        "synth_tuples": 100,
        "auto_instance_cache_model": False,
        "clean_with_user_input": True,
        "gpdep_threshold": 0.3,
        "training_time_limit": 30,
        "feature_generators": ["llm_correction"],
        "classification_model": "ABC",
        "vicinity_orders": [1, 2],
        "vicinity_feature_generator": "pdep",
        "n_rows": None,
        "n_best_pdeps": 3,
        "synth_cleaning_threshold": 0.9,
        "test_synth_data_direction": "user_data",
        "pdep_features": ['pr'],
        "fd_feature": "pr",
        },
        runs=3
    )

    renuver_configs = combine_configs(
        ranges={
        "dataset": ['bridges', 'cars', 'glass', 'restaurant'],
        "error_fraction": [1, 3],
        },
        config={
        "dataset": "1481",
        "error_class": "simple_mcar",
        "error_fraction": 1,
        "labeling_budget": 20,
        "synth_tuples": 100,
        "auto_instance_cache_model": False,
        "clean_with_user_input": True,
        "gpdep_threshold": 0.3,
        "training_time_limit": 30,
        "feature_generators": ["llm_correction"],
        "classification_model": "ABC",
        "vicinity_orders": [1, 2],
        "vicinity_feature_generator": "pdep",
        "n_rows": None,
        "n_best_pdeps": 3,
        "synth_cleaning_threshold": 0.9,
        "test_synth_data_direction": "user_data",
        "pdep_features": ['pr'],
        "fd_feature": "pr",
        },
        runs=3
    )

    openml_configs = combine_configs(
        ranges={
            "dataset": ["6", "137", "184", "1481", "41027", "43572"],
            "error_fraction": [1, 5],
            "error_class": ["simple_mcar", "imputer_simple_mcar"],
        },
        config={
        "dataset": "1481",
        "error_class": "simple_mcar",
        "error_fraction": 1,
        "labeling_budget": 20,
        "synth_tuples": 100,
        "auto_instance_cache_model": False,
        "clean_with_user_input": True,
        "gpdep_threshold": 0.3,
        "training_time_limit": 30,
        "feature_generators": ["llm_correction"],
        "classification_model": "ABC",
        "vicinity_orders": [1, 2],
        "vicinity_feature_generator": "pdep",
        "n_rows": 1000,
        "n_best_pdeps": 3,
        "synth_cleaning_threshold": 0.9,
        "test_synth_data_direction": "user_data",
        "pdep_features": ['pr'],
        "fd_feature": "pr",
        },
        runs=3
    )

    # merge configs
    configs = [*baran_configs, *renuver_configs, *openml_configs]

    jobs_path = Path('jobs/')
    jobs_path.mkdir(parents=True, exist_ok=True)

    # delete files in jobs/ directory
    for file_path in jobs_path.iterdir():
        if file_path.is_file():
            file_path.unlink()

    i = 0
    for i, config in enumerate(configs):
        generat_job(config, experiment_name, jobs_path)

    print(f'Generated {i} jobs and stored them to {jobs_path}/.')


if __name__ == "__main__":
    main()