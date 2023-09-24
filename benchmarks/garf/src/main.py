import json
import traceback
from argparse import ArgumentParser
from pathlib import Path

import config
from att_reverse import att_reverse
from rule_sample import rule_sample
from SeqGAN.train import Trainer
from eva import evaluate


def run(
    dataset_name: str,
    results_path: Path,
) -> None:
    print("Starting baseline with arguments ...")
    print(f"\t--dataset_name={dataset_name}")
    print(f"\t--results_path={results_path}")

    ##### GARF #####
    models_path = Path('models/')
    table_name_clean = dataset_name
    table_name_corrected = f'{dataset_name}_copy'
    table_name_dirty = f'{dataset_name}_dirty'


    models_base_path = (models_path / dataset_name)
    models_base_path.mkdir(parents=True, exist_ok=True)

    g_pre_weights_path = models_base_path / "generator_pre.hdf5"
    d_pre_weights_path = models_base_path / "discriminator_pre.hdf5"
    g_weights_path = models_base_path / "generator.pkl"
    d_weights_path = models_base_path / "discriminator.hdf5"
    path_neg = models_base_path / "generated_sentences.txt"
    path_rules = models_base_path / "rules.txt"

    if not Path("database.db").exists():
        raise ValueError('No sqlite3 database found. Make sure to create the database before running GARF.')

    try:
        for order in [1, 0]:
            att_reverse(dataset_name, order, models_base_path)

            trainer = Trainer(
                order=order,
                B=config.batch_size,
                T=config.max_length,
                g_E=config.g_e,
                g_H=config.g_h,
                d_E=config.d_e,
                d_H=config.d_h,
                d_dropout=config.d_dropout,
                generate_samples=config.generate_samples,
                path_pos=dataset_name,
                path_neg=path_neg,
                path_rules=path_rules,
                g_lr=config.g_lr,
                d_lr=config.d_lr,
                n_sample=config.n_sample,
                models_base_path=models_base_path,
            )

            trainer.pre_train(
                g_epochs=config.g_pre_epochs,
                d_epochs=config.d_pre_epochs,
                g_pre_path=g_pre_weights_path,
                d_pre_path=d_pre_weights_path,
                g_lr=config.g_pre_lr,
                d_lr=config.d_pre_lr,
            )

            trainer.load_pre_train(g_pre_weights_path, d_pre_weights_path)
            trainer.reflect_pre_train()  # Mapping layer weights to agent

            trainer.train(
                steps=1,
                g_steps=1,
                head=10,
                g_weights_path=g_weights_path,
                d_weights_path=d_weights_path,
            )
            trainer.save(g_weights_path, d_weights_path)

            rule_len = rule_sample(path_rules, dataset_name, order)
            trainer.train_rules(rule_len, path_rules)
            trainer.filter(dataset_name)
            att_reverse(dataset_name, 1, models_base_path)
            trainer.repair(dataset_name)

    except Exception as e:
        exception_type = str(type(e).__name__)
        exception_message = str(e)
        exception_traceback = traceback.format_exc()

        # Create a dictionary to store the exception information
        exception_data = {
            "dataset_name": dataset_name,
            "exception_type": exception_type,
            "exception_message": exception_message,
            "exception_traceback": exception_traceback,
        }

        # Convert the dictionary to a JSON string
        json_data = json.dumps(exception_data, indent=4)

        # Write the JSON string to a text file

        with open(f'output/{table_name_clean}_result.txt', 'wt') as file:
            file.write(json_data)
        print('Did not clean data successfully:')
        print(f'{exception_type}: {exception_message}')

    ### END GARF ###

    # evaluate results

    evaluate(table_name_clean, table_name_corrected, table_name_dirty)

    ##### GARF END #####


if __name__ == "__main__":
    parser = ArgumentParser(description="CLI to start a data-cleaning baseline 'garf'.")
    parser.add_argument("--dataset_name", type=str, required=True)
    parser.add_argument("--results_path", type=Path, required=True)

    parameter_as_dict = {parameter: value for parameter, value in vars(parser.parse_args()).items()}

    run(**parameter_as_dict)
