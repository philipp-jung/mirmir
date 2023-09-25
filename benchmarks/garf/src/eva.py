import json
import sqlite3
import pandas as pd
from typing import Dict, Tuple


def get_dataframes_difference(df_1: pd.DataFrame, df_2: pd.DataFrame) -> Dict:
    """
    This method compares two dataframes df_1 and df_2. It returns a dictionary whose keys are the coordinates of
    a cell. The corresponding value is the value in df_1 at the cell's position if the values of df_1 and df_2 are
    not the same at the given position.
    """
    if df_1.shape != df_2.shape:
        raise ValueError("Two compared datasets do not have equal sizes.")
    difference_dictionary = {}
    for row in range(df_1.shape[0]):
        for col in range(df_1.shape[1]):
            if df_1.iloc[row, col] != df_2.iloc[row, col]:
                difference_dictionary[(row, col)] = df_1.iloc[row, col]
    return difference_dictionary


def get_actual_errors_dictionary_ground_truth(df_clean, df_dirty) -> Dict[Tuple[int, int], str]:
    """
    Returns a dictionary that resolves every error cell to the ground truth.
    """
    return get_dataframes_difference(df_clean, df_dirty)


def get_data_cleaning_evaluation(df_clean, df_dirty, df_corrected):
    """
    This method evaluates data cleaning process.
    """
    actual_errors = get_actual_errors_dictionary_ground_truth(df_clean, df_dirty)
    correction_dictionary = get_dataframes_difference(df_corrected, df_dirty)
    ed_tp = 0.0
    ec_tp = 0.0
    output_size = 0.0
    for cell in correction_dictionary:
        output_size += 1
        if cell in actual_errors:
            ed_tp += 1.0
            if correction_dictionary[cell] == actual_errors[cell]:
                ec_tp += 1.0
    ed_p = 0.0 if output_size == 0 else ed_tp / output_size
    ed_r = 0.0 if len(actual_errors) == 0 else ed_tp / len(actual_errors)
    ed_f = 0.0 if (ed_p + ed_r) == 0.0 else (2 * ed_p * ed_r) / (ed_p + ed_r)
    ec_p = 0.0 if output_size == 0 else ec_tp / output_size
    ec_r = 0.0 if len(actual_errors) == 0 else ec_tp / len(actual_errors)
    ec_f = 0.0 if (ec_p + ec_r) == 0.0 else (2 * ec_p * ec_r) / (ec_p + ec_r)
    return [ed_p, ed_r, ed_f, ec_p, ec_r, ec_f]


def get_table_as_df(table_name, conn):
    df = (pd.read_sql_query(f'SELECT * FROM {table_name}', conn)
                .drop(columns="Label")
                .astype(str))
    return df


def evaluate(table_name_clean, table_name_corrected, table_name_dirty):
    conn = sqlite3.connect('database.db')
    df_clean = get_table_as_df(table_name_clean, conn)
    df_dirty = get_table_as_df(table_name_dirty, conn)
    df_corrected = get_table_as_df(table_name_corrected, conn)
    conn.close()

    ed_p, ed_r, ed_f, ec_p, ec_r, ec_f = get_data_cleaning_evaluation(df_clean, df_dirty, df_corrected)

    with open(f'output/{table_name_clean}_result.txt', 'wt') as f:
        f.write(json.dumps({
                'dataset': table_name_clean,
                'ed_p': ed_p,
                'ed_r': ed_r,
                'ed_f': ed_f,
                'ec_p': ec_p,
                'ec_r': ec_r,
                'ec_f': ec_f,
            })
        )
    print("Cleaning performance on {}:\nPrecision = {:.2f}\nRecall = {:.2f}\nF1 = {:.2f}".format(table_name_clean, ec_p, ec_r, ec_f))



if __name__ == '__main__':

    flag = 2
    if flag == 1:
        table_name_clean = "Test"  # Hosp_rules
        table_name_corrected = "Test_copy"  #
    if flag == 2:
        table_name_clean = "Hosp_rules"  #
        table_name_corrected = "Hosp_rules_copy"
    if flag == 3:
        table_name_clean = "UIS"  #
        table_name_corrected = "UIS_copy"

    if flag == 4:
        table_name_clean = "Food"  #
        table_name_corrected = "Food_copy"

    evaluate(table_name_clean,table_name_corrected)
