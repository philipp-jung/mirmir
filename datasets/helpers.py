import random
import pandas as pd


def simple_mcar(df: pd.DataFrame, fraction: float, error_token=None, error_token_int=-9999999, error_token_obj=''):
    """
    Randomly insert missing values into a dataframe. Note that specifying the
    error_token as None preserves dtypes in the dataframe. If the error token
    is a string or a number, make sure to cast the entire dataframe to a dtype
    supporting categorical data with `df.astype(str)`. You will run into errors
    otherwise.

    Copies df, so that the clean dataframe you pass doesn't get corrupted
    in place.

    Note that casting to categorical data does mess up the imputer feature
    generator.
    """
    df_dirty = df.copy()
    n_rows, n_cols = df.shape

    if fraction > 1:
        raise ValueError("Cannot turn more than 100% of the values into errors.")
    target_corruptions = round(n_rows * n_cols * fraction)
    error_cells = random.sample(
        [(x, y) for x in range(n_rows) for y in range(n_cols)],
        k=target_corruptions,
    )

    # replace with missing value token in a way that preserves dtypes.
    for x, y in error_cells:
        column_dtype = df_dirty.iloc[:, y].dtype
        if column_dtype == 'int64':
            df_dirty.iat[x, y] = error_token_int
        elif column_dtype in ['object', 'str', 'string']:
            df_dirty.iat[x, y] = error_token_obj
        else:
            error_token = error_token

    return df_dirty


def simple_mcar_column(se: pd.Series, fraction: float, error_token=None):
    """
    Randomly insert missing values into a pandas Series. See docs on
    simple_mcar for more information.

    Copies the passed Series `se`, and returns it.
    """
    se_corrupt = se.copy()
    n_rows = se.shape[0]
    target_corruptions = round(n_rows * fraction)
    error_positions = random.sample([x for x in range(n_rows)], k=target_corruptions)
    for x in error_positions:
        se_corrupt.iat[x] = error_token
    return se_corrupt
