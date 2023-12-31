import os
import math
import json
import pickle
import random
import difflib
import unicodedata
import multiprocessing
from itertools import combinations

import numpy as np
import sklearn.svm
import sklearn.ensemble
import sklearn.linear_model
import sklearn.tree
import sklearn.feature_selection

from typing import Dict, List, Union, Tuple
import pandas as pd

import dataset
import auto_instance
import pdep
import hpo
import helpers
import ml_helpers


class Cleaning:
    """
    Class that carries out the error correction process.
    """

    def __init__(self, labeling_budget: int, classification_model: str, clean_with_user_input: bool, feature_generators: List[str],
                 vicinity_orders: List[int], vicinity_feature_generator: str, auto_instance_cache_model: bool,
                 n_best_pdeps: int, training_time_limit: int,
                 synth_tuples: int, synth_cleaning_threshold: float,
                 test_synth_data_direction: str, pdep_features: Tuple[str], gpdep_threshold: float, fd_feature: str,
                 domain_model_threshold: float, dataset_analysis: bool = False):
        """
        Parameters of the cleaning experiment.
        @param labeling_budget: How many tuples are labeled by the user. In the Baran publication, 20  labels are frequently used.
        @param classification_model: "ABC" for sklearn's AdaBoostClassifier with n_estimators=100, "CV" for
        cross-validation. Default is "ABC".
        @param clean_with_user_input: Take user input to clean data with. This will always improve cleaning performance,
        and is recommended to set to True as the default value. Handy to disable when debugging models.
        @param feature_generators: Six feature generators are available: 'auto_instance', 'domain_instance', 'fd', 'vicinity',
        'llm"master', 'llm_correction'.  Pass them as strings in a list to make Mimir use them, e.g.
        ['domain_instance', 'vicinity', 'auto_instance'].
        @param vicinity_orders: The pdep approach enables the usage of higher-order dependencies to clean data. Each
        order used is passed as an integer, e.g. [1, 2]. Unary dependencies would be used by passing [1] for example.
        @param vicinity_feature_generator: How vicinity features are generated. Either 'pdep' or 'naive'. Baran uses
        'naive' by default.
        @param auto_instance_cache_model: Whether or not the AutoGluon model used in the auto_instance model is stored after
        training and used from cache. Otherwise, a model is retrained with every user-provided tuple. If true, reduces
        cleaning time significantly.
        @param n_best_pdeps: When using vicinity_feature_generator = 'pdep', dependencies are ranked via the pdep
        measure. After ranking, the n_best_pdeps dependencies are used to provide cleaning suggestions. A good heuristic
        is to set this to 3.
        @param training_time_limit: Limit in seconds of how long the AutoGluon imputer model is trained.
        @param synth_tuples: maximum number of tuples to infer training data from.
        @param synth_cleaning_threshold: Threshold for column-cleaning to pass in order to leverage synth-data.
        Deactivates if set to -1.
        @param test_synth_data_direction: Direction in which the synth data's usefulness for cleaning is being tested.
        Set either to 'user_data' to clean user-data with synth-data. Or 'synth_data' to clean synth-data with
        user-inputs.
        @param pdep_features: List of features the pdep-feature-generator will return. Can be
        'pr' for conditional probability, 'vote' for how many FDs suggest the correction, 'pdep' for the
        pdep-score of the dependency providing the correction, and 'gpdep' for the gpdep-socre of said
        dependency.
        @param gpdep_threshold: Threshold a suggestion's gpdep score must pass before it is used to generate a feature.
        @param fd_feature: Feature used by the the fd_instance imputer to make cleaning suggestions. Choose from ('gpdep', 'pdep', 'fd').
        @param domain_model_threshold: If a value model's correction suggestion's pr is smaller than the threshold, it is discarded.
        @param dataset_analysis: Write a detailed analysis of how Mimir cleans a a dataset to a .json file.
        """

        self.SYNTH_TUPLES = synth_tuples
        self.CLEAN_WITH_USER_INPUT = clean_with_user_input

        self.FEATURE_GENERATORS = feature_generators
        self.VICINITY_ORDERS = vicinity_orders
        self.VICINITY_FEATURE_GENERATOR = vicinity_feature_generator
        self.AUTO_INSTANCE_CACHE_MODEL = auto_instance_cache_model
        self.N_BEST_PDEPS = n_best_pdeps
        self.TRAINING_TIME_LIMIT = training_time_limit
        self.CLASSIFICATION_MODEL = classification_model
        self.SYNTH_CLEANING_THRESHOLD = synth_cleaning_threshold
        self.TEST_SYNTH_DATA_DIRECTION = test_synth_data_direction
        self.PDEP_FEATURES = pdep_features
        self.GPDEP_THRESHOLD = gpdep_threshold
        self.FD_FEATURE = fd_feature
        self.DOMAIN_MODEL_THRESHOLD = domain_model_threshold
        self.DATASET_ANALYSIS = dataset_analysis
        self.MAX_VALUE_LENGTH = 50
        self.LABELING_BUDGET = labeling_budget

        # TODO remove unused attributes
        self.IGNORE_SIGN = "<<<IGNORE_THIS_VALUE>>>"
        self.VERBOSE = False
        self.SAVE_RESULTS = False

        # variable for debugging CV
        self.sampled_tuples = 0

    @staticmethod
    def _to_model_adder(model, key, value):
        """
        This method incrementally adds a key-value into a dictionary-implemented model.
        """
        if key not in model:
            model[key] = {}
        if value not in model[key]:
            model[key][value] = 0.0
        model[key][value] += 1.0

    @staticmethod
    def _value_encoder(value, encoding):
        """
        This method represents a value with a specified value abstraction encoding method.
        """
        if encoding == "identity":
            return json.dumps(list(value))
        if encoding == "unicode":
            return json.dumps([unicodedata.category(c) for c in value])

    def _domain_based_model_updater(self, model, ud):
        """
        This method updates the domain_instance-based error corrector model with a given update dictionary.
        """
        self._to_model_adder(model, ud["column"], ud["new_value"])

    def _value_based_models_updater(self, models, ud):
        """
        This method updates the value-based error corrector models with a given update dictionary.
        """
        remover_transformation = {}
        adder_transformation = {}
        replacer_transformation = {}
        s = difflib.SequenceMatcher(None, ud["old_value"], ud["new_value"])
        for tag, i1, i2, j1, j2 in s.get_opcodes():
            index_range = json.dumps([i1, i2])
            if tag == "delete":
                remover_transformation[index_range] = ""
            if tag == "insert":
                adder_transformation[index_range] = ud["new_value"][j1:j2]
            if tag == "replace":
                replacer_transformation[index_range] = ud["new_value"][j1:j2]
        for encoding in ["identity", "unicode"]:
            encoded_old_value = self._value_encoder(ud["old_value"], encoding)
            if remover_transformation:
                self._to_model_adder(models[0], encoded_old_value, json.dumps(remover_transformation))
            if adder_transformation:
                self._to_model_adder(models[1], encoded_old_value, json.dumps(adder_transformation))
            if replacer_transformation:
                self._to_model_adder(models[2], encoded_old_value, json.dumps(replacer_transformation))
            self._to_model_adder(models[3], encoded_old_value, ud["new_value"])

    def _imputer_based_corrector(self, model: Dict[int, pd.DataFrame], ed: dict) -> Dict[str, float]:
        """
        Use class probabilities generated by an Datawig model to make corrections.

        @param model: Dictionary with an AutoGluonImputer per column. Will an empty dict if no models have been trained.
        @param ed: Error Dictionary with information on the error and its vicinity.
        @return: list of corrections.
        """
        df_probas = model.get(ed['column'])
        if df_probas is None:
            return {}

        se_probas = df_probas.iloc[ed['row']]  # select error position
        prob_d = {key: se_probas.to_dict()[key] for key in se_probas.to_dict()}

        # sometimes autogluon returns np.nan, which the ensemble classifier downstream chokes up on.
        result = {correction: 0.0 if np.isnan(pr) else pr for correction, pr in prob_d.items() if correction != ed['old_value']}
        return result

    def _value_based_corrector(self, models, ed):
        """
        This method takes the value-based models and an error dictionary to generate potential value-based corrections.
        """
        results = {'remover': [], 'adder': [], 'replacer': [], 'swapper': []}
        for m, model_name in enumerate(["remover", "adder", "replacer", "swapper"]):
            model = models[m]
            for encoding in ["identity", "unicode"]:
                results_dictionary = {}
                encoded_value_string = self._value_encoder(ed["old_value"], encoding)
                if encoded_value_string in model:
                    sum_scores = sum(model[encoded_value_string].values())
                    if model_name in ["remover", "adder", "replacer"]:
                        for transformation_string in model[encoded_value_string]:
                            index_character_dictionary = {i: c for i, c in enumerate(ed["old_value"])}
                            transformation = json.loads(transformation_string)
                            for change_range_string in transformation:
                                change_range = json.loads(change_range_string)
                                if model_name in ["remover", "replacer"]:
                                    for i in range(change_range[0], change_range[1]):
                                        index_character_dictionary[i] = ""
                                if model_name in ["adder", "replacer"]:
                                    ov = "" if change_range[0] not in index_character_dictionary else \
                                        index_character_dictionary[change_range[0]]
                                    index_character_dictionary[change_range[0]] = transformation[change_range_string] + ov
                            new_value = ""
                            for i in range(len(index_character_dictionary)):
                                new_value += index_character_dictionary[i]
                            pr = model[encoded_value_string][transformation_string] / sum_scores
                            results_dictionary[new_value] = pr
                    if model_name == "swapper":
                        for new_value in model[encoded_value_string]:
                            pr = model[encoded_value_string][new_value] / sum_scores
                            results_dictionary[new_value] = pr
                results[model_name].append(results_dictionary)
        return results

    def _domain_based_corrector(self, model, ed):
        """
        This method takes a domain_instance-based model and an error dictionary to generate potential domain_instance-based corrections.
        """
        results_dictionary = {}
        value_counts = model.get(ed["column"])
        if value_counts is not None:
            sum_scores = sum(model[ed["column"]].values())
            for new_value in model[ed["column"]]:
                pr = model[ed["column"]][new_value] / sum_scores
                results_dictionary[new_value] = pr
                if pr >= self.DOMAIN_MODEL_THRESHOLD:
                    results_dictionary[new_value] = pr
        return results_dictionary

    def initialize_dataset(self, d):
        """
        This method initializes the dataset.
        """
        d.results_folder = os.path.join(os.path.dirname(d.path), "mirmir-results-" + d.name)
        if self.SAVE_RESULTS and not os.path.exists(d.results_folder):
            os.mkdir(d.results_folder)
        d.labeled_tuples = {} if not hasattr(d, "labeled_tuples") else d.labeled_tuples
        d.labeled_cells = {} if not hasattr(d, "labeled_cells") else d.labeled_cells
        d.corrected_cells = {} if not hasattr(d, "corrected_cells") else d.corrected_cells
        return d

    def initialize_models(self, d):
        """
        This method initializes the error corrector models.
        """
        d.domain_models = {}

        for row in d.dataframe.itertuples():
            i, row = row[0], row[1:]
            # Das ist richtig cool: Jeder Wert des Tupels wird untersucht und
            # es wird überprüft, ob dieser Wert ein aus Error Detection bekannter
            # Fehler ist. Wenn dem so ist, wird der Wert durch das IGNORE_SIGN
            # ersetzt.
            vicinity_list = [cv if (i, cj) not in d.detected_cells else self.IGNORE_SIGN for cj, cv in enumerate(row)]
            for j, value in enumerate(row):
                # if rhs_value's position is not a known error
                if (i, j) not in d.detected_cells:
                    temp_vicinity_list = list(vicinity_list)
                    temp_vicinity_list[j] = self.IGNORE_SIGN
                    update_dictionary = {
                        "column": j,
                        "new_value": value,
                    }
                    self._domain_based_model_updater(d.domain_models, update_dictionary)

        # Initialize LLM cache
        conn = helpers.connect_to_cache()
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS cache
                          (dataset TEXT,
                          row INT,
                          column INT,
                          correction_model TEXT,
                          correction_tokens TEXT,
                          token_logprobs TEXT,
                          top_logprobs TEXT)''')
        conn.commit()

        # Correction store for feature creation
        corrections_features = []  # don't need further processing being used in ensembling.

        for feature in self.FEATURE_GENERATORS:
            if feature == 'vicinity':
                if self.VICINITY_FEATURE_GENERATOR == 'pdep':
                    for o in self.VICINITY_ORDERS:
                        corrections_features.append(f'vicinity_{o}')
                elif self.VICINITY_FEATURE_GENERATOR == 'naive':  # every lhs combination creates a feature
                    _, cols = d.dataframe.shape
                    for o in self.VICINITY_ORDERS:
                        for lhs in combinations(range(cols), o):
                            corrections_features.append(f'vicinity_{o}_{str(lhs)}')
            elif feature == 'value':
                models = ['remover', 'adder', 'replacer', 'swapper']
                encodings = ['identity', 'unicode']
                models_names = [f"value_{m}_{e}" for m in models for e in encodings]
                corrections_features.extend(models_names)
            else:
                corrections_features.append(feature)

        d.corrections = helpers.Corrections(corrections_features)
        d.inferred_corrections = helpers.Corrections(corrections_features)

        d.vicinity_models = {}
        d.value_models = [{}, {}, {}, {}]

        d.lhs_values_frequencies = {}
        if 'vicinity' in self.FEATURE_GENERATORS:
            for o in self.VICINITY_ORDERS:
                d.vicinity_models[o], d.lhs_values_frequencies[o] = pdep.mine_all_counts(
                    df=d.dataframe,
                    detected_cells=d.detected_cells,
                    order=o,
                    ignore_sign=self.IGNORE_SIGN)
        d.imputer_models = {}

    def sample_tuple(self, d, random_seed):
        """
        This method samples a tuple.

        I also added two tiers of columns to choose samples from. Either, there are error cells
        for which no correction suggestion has been made yet. In that case, we sample from these error cells.
        If correction suggestions have been made for all cells, we sample from error cells that have not been
        sampled before.
        """
        rng = np.random.default_rng(seed=random_seed)
        remaining_column_unlabeled_cells = {}
        remaining_column_unlabeled_cells_error_values = {}
        remaining_column_uncorrected_cells = {}
        remaining_column_uncorrected_cells_error_values = {}

        error_positions = helpers.ErrorPositions(d.detected_cells, d.dataframe.shape, d.labeled_cells)

        column_errors = error_positions.original_column_errors()

        for j in column_errors:
            for error_cell in column_errors[j]:
                if error_cell not in d.corrected_cells:  # no correction suggestion has been found yet.
                    self._to_model_adder(remaining_column_uncorrected_cells, j, error_cell)
                    self._to_model_adder(remaining_column_uncorrected_cells_error_values, j,
                                         d.dataframe.iloc[error_cell])
                if error_cell not in d.labeled_cells:
                    # the cell has not been labeled by the user yet. this is stricter than the above condition.
                    self._to_model_adder(remaining_column_unlabeled_cells, j, error_cell)
                    self._to_model_adder(remaining_column_unlabeled_cells_error_values, j, d.dataframe.iloc[error_cell])
        tuple_score = np.ones(d.dataframe.shape[0])
        tuple_score[list(d.labeled_tuples.keys())] = 0.0

        if len(remaining_column_uncorrected_cells) > 0:
            remaining_columns_to_choose_from = remaining_column_uncorrected_cells
            remaining_cell_error_values = remaining_column_uncorrected_cells_error_values
        else:
            remaining_columns_to_choose_from = remaining_column_unlabeled_cells
            remaining_cell_error_values = remaining_column_unlabeled_cells_error_values

        for j in remaining_columns_to_choose_from:
            for cell in remaining_columns_to_choose_from[j]:
                value = d.dataframe.iloc[cell]
                column_score = math.exp(len(remaining_columns_to_choose_from[j]) / len(column_errors[j]))
                cell_score = math.exp(remaining_cell_error_values[j][value] / len(remaining_columns_to_choose_from[j]))
                tuple_score[cell[0]] *= column_score * cell_score

        # Nützlich, um tuple-sampling zu debuggen: Zeigt die Tupel, aus denen
        # zufällig gewählt wird.
        # print(np.argwhere(tuple_score == np.amax(tuple_score)).flatten())
        d.sampled_tuple = rng.choice(np.argwhere(tuple_score == np.amax(tuple_score)).flatten())
        self.sampled_tuples += 1

    def label_with_ground_truth(self, d):
        """
        This method labels a tuple with ground truth.
        Takes the sampled row from d.sampled_tuple, iterates over each cell
        in that row taken from the clean data, and then adds
        d.labeled_cells[(row, col)] = [is_error, clean_value_from_clean_dataframe]
        to d.labeled_cells.
        """
        d.labeled_tuples[d.sampled_tuple] = 1
        for col in range(d.dataframe.shape[1]):
            cell = (d.sampled_tuple, col)
            error_label = 0
            if d.dataframe.iloc[cell] != d.clean_dataframe.iloc[cell]:
                error_label = 1
            d.labeled_cells[cell] = [error_label, d.clean_dataframe.iloc[cell]]

    def update_models(self, d):
        """
        This method updates the error corrector models with a new labeled tuple.
        """
        cleaned_sampled_tuple = []
        for column in range(d.dataframe.shape[1]):
            clean_cell = d.labeled_cells[(d.sampled_tuple, column)][1]
            cleaned_sampled_tuple.append(clean_cell)

        for column in range(d.dataframe.shape[1]):
            cell = (d.sampled_tuple, column)
            update_dictionary = {
                "column": column,
                "old_value": d.dataframe.iloc[cell],
                "new_value": cleaned_sampled_tuple[column],
            }

            # if the value in that cell has been labeled an error
            if d.labeled_cells[cell][0] == 1:  # update domain and value models.
                if 'domain' in self.FEATURE_GENERATORS:
                    self._domain_based_model_updater(d.domain_models, update_dictionary)
                if 'value' in self.FEATURE_GENERATORS:
                    self._value_based_models_updater(d.value_models, update_dictionary)

                # if the cell hadn't been detected as an error
                if cell not in d.detected_cells:
                    # add that cell to detected_cells and assign it IGNORE_SIGN
                    # --> das passiert, wenn die Error Detection nicht perfekt
                    # war, dass man einen Fehler labelt, der vorher noch nicht
                    # gelabelt war.
                    d.detected_cells[cell] = self.IGNORE_SIGN

        if 'vicinity' in self.FEATURE_GENERATORS:
            for o in self.VICINITY_ORDERS:
                pdep.update_vicinity_model(counts_dict=d.vicinity_models[o],
                                           lhs_values=d.lhs_values_frequencies[o],
                                           clean_sampled_tuple=cleaned_sampled_tuple,
                                           error_positions=d.detected_cells,
                                           row=d.sampled_tuple)

        if self.VERBOSE:
            print("The user labeled an additional tuple: {}.".format(d.sampled_tuple))

    def _feature_generator_process(self, args) -> List[Tuple[Tuple[int, int], str, Union[str, None]]]:
        """
        This method generates cleaning suggestions for one error in one cell. The suggestion
        gets turned into features for the classifier in predict_corrections(). It gets called
        once for each error cell.

        Depending on the value of `synchronous` in `generate_features()`, the method will
        be executed in parallel or not.

        Returns a List of Tuples with the structure (error_cell, cleaning_model_name, prompt), where prompt is to be
        sent to openai to clean cell error_cell using the approach called cleaning_model_name.
        """
        ai_prompts: List[Tuple[Tuple[int, int], str, Union[str, None]]] = []
        d, error_cell, is_synth = args

        # vicinity ist die Zeile, column ist die Zeilennummer, old_value ist der Fehler
        error_dictionary = {"column": error_cell[1],
                            "old_value": d.dataframe.iloc[error_cell],
                            "vicinity": list(d.dataframe.iloc[error_cell[0], :]),
                            "row": error_cell[0]}

        if "fd" in self.FEATURE_GENERATORS:
            fd_corrections = pdep.fd_based_corrector(d.fd_inverted_gpdeps, d.fd_counts_dict, error_dictionary, self.FD_FEATURE)
            if is_synth:
                d.inferred_corrections.get('fd')[error_cell] = fd_corrections
            else:
                d.corrections.get('fd')[error_cell] = fd_corrections

        if "vicinity" in self.FEATURE_GENERATORS:
            if self.VICINITY_FEATURE_GENERATOR == 'naive':
                for o in self.VICINITY_ORDERS:
                    naive_corrections = pdep.vicinity_based_corrector_order_n(
                        counts_dict=d.vicinity_models[o],
                        ed=error_dictionary)
                    if is_synth:
                        for lhs in naive_corrections:
                            d.inferred_corrections.get(f'vicinity_{o}_{str(lhs)}')[error_cell] = naive_corrections[lhs]
                    else:
                        for lhs in naive_corrections:
                            d.corrections.get(f'vicinity_{o}_{str(lhs)}')[error_cell] = naive_corrections[lhs]

            elif self.VICINITY_FEATURE_GENERATOR == 'pdep':
                for o in self.VICINITY_ORDERS:
                    pdep_corrections = pdep.pdep_vicinity_based_corrector(
                        inverse_sorted_gpdeps=d.inv_vicinity_gpdeps[o],
                        counts_dict=d.vicinity_models[o],
                        ed=error_dictionary,
                        n_best_pdeps=self.N_BEST_PDEPS,
                        features_selection=self.PDEP_FEATURES,
                        gpdep_threshold=self.GPDEP_THRESHOLD)
                    if is_synth:
                        d.inferred_corrections.get(f'vicinity_{o}')[error_cell] = pdep_corrections
                    else:
                        d.corrections.get(f'vicinity_{o}')[error_cell] = pdep_corrections
            else:
                raise ValueError(f'Unknown VICINITY_FEATURE_GENERATOR '
                                 f'{self.VICINITY_FEATURE_GENERATOR}')

        if 'llm_correction' in self.FEATURE_GENERATORS and not is_synth and len(d.labeled_tuples) == self.LABELING_BUDGET:
            """
            Use large language model to correct an error based on the error value.
            """
            if error_dictionary['old_value'] != '':  # If there is no value to be transformed, skip.
                error_positions = helpers.ErrorPositions(d.detected_cells, d.dataframe.shape, d.labeled_cells)
                column_errors_positions = error_positions.original_column_errors().get(error_dictionary['column'], [])
                column_errors_rows = [row for (row, col) in column_errors_positions]

                # Construct pairs of ('error', 'correction') by iterating over the user input.
                error_correction_pairs: List[Tuple[str, str]] = []
                for labeled_row in d.labeled_tuples:
                    if labeled_row in column_errors_rows:
                        cell = labeled_row, error_dictionary['column']
                        error = d.dataframe.iloc[cell]
                        correction = d.labeled_cells[cell][1]
                        if error != '':
                            if correction == '':  # encode missing value
                                correction = '<MV>'
                            error_correction_pairs.append((error, correction))

                # Only do llm_correction cleaning if there is an example for cleaning that column.
                if len(error_correction_pairs) > 0:
                    prompt = "You are a data cleaning machine that detects patterns to return a correction. If you do "\
                             "not find a correction, you return the token <NULL>. You always follow the example.\n---\n"
                    n_pairs = min(10, len(error_correction_pairs))
                    for (error, correction) in random.sample(error_correction_pairs, n_pairs):
                        prompt = prompt + f"error:{error}" + '\n' + f"correction:{correction}" + '\n'
                    prompt = prompt + f"error:{error_dictionary['old_value']}" + '\n' + "correction:"
                    ai_prompts.append((error_cell, 'llm_correction', prompt))

        if 'llm_master' in self.FEATURE_GENERATORS and len(d.labeled_tuples) == self.LABELING_BUDGET:
            # use large language model to correct an error based on the error's vicinity. Inspired by Narayan et al.
            # 2022.
            if not is_synth:
                error_positions = helpers.ErrorPositions(d.detected_cells, d.dataframe.shape, d.labeled_cells)
                row_errors = error_positions.updated_row_errors()
                rows_without_errors = [i for i in range(d.dataframe.shape[0]) if len(row_errors[i]) == 0]
                if len(rows_without_errors) >= 3:
                    prompt = "You are a data cleaning machine that returns a correction, which is a single expression. If "\
                             "you do not find a correction, return the token <NULL>. You always follow the example.\n---\n"
                    n_pairs = min(5, len(rows_without_errors))
                    rows = random.sample(rows_without_errors, n_pairs)
                    for row in rows:
                        row_as_string, correction = helpers.error_free_row_to_prompt(d.dataframe, row, error_dictionary['column'])
                        prompt = prompt + row_as_string + '\n' + f'correction:{correction}' + '\n'
                    final_row_as_string, _ = helpers.error_free_row_to_prompt(d.dataframe, error_dictionary['row'], error_dictionary['column'])
                    prompt = prompt + final_row_as_string + '\n' + 'correction:'
                    ai_prompts.append((error_cell, 'llm_master', prompt))
            else:  # synth - return empty prompts and use cache to make cleaning suggestions due to API cost.
                # ai_prompts.append((error_cell, 'llm_master', ''))
                pass

        if "domain_instance" in self.FEATURE_GENERATORS:
            if is_synth:
                d.inferred_corrections.get('domain_instance')[error_cell] = self._domain_based_corrector(d.domain_models, error_dictionary)
            else:
                d.corrections.get('domain_instance')[error_cell] = self._domain_based_corrector(d.domain_models, error_dictionary)

        if "value" in self.FEATURE_GENERATORS:
            if not is_synth:
                value_correction_suggestions = self._value_based_corrector(d.value_models, error_dictionary)
                if error_cell == (0,4):
                    a = 1
                for model_name, encodings_list in value_correction_suggestions.items():
                    for encoding, correction_suggestions in zip(['identity', 'unicode'], encodings_list):
                        d.corrections.get(f'value_{model_name}_{encoding}')[error_cell] = correction_suggestions

        if "auto_instance" in self.FEATURE_GENERATORS:
            imputer_corrections = self._imputer_based_corrector(d.imputer_models, error_dictionary)

            # Sometimes training an auto_instance model fails for a column, while it succeeds on other columns.
            # If training failed for a column, imputer_corrections will be an empty list. Which will lead
            # to one less feature being added to values in that column. Which in turn is bad news in the ensemble.
            # To prevent this, I have imputer_corrections fall back to {}, which has length 1 and will create
            # a feature.
            if len(d.labeled_tuples) == self.LABELING_BUDGET and len(imputer_corrections) == 0:
                imputer_corrections = {}
            if is_synth:
                d.inferred_corrections.get('auto_instance')[error_cell] = imputer_corrections
            else:
                d.corrections.get('auto_instance')[error_cell] = imputer_corrections
        return ai_prompts

    def prepare_augmented_models(self, d):
        """
        Prepare Mimir's augmented models:
        1) Calculate gpdeps and append them to d.
        2) Train auto_instance model for each column.
        """

        shape = d.dataframe.shape
        error_positions = helpers.ErrorPositions(d.detected_cells, shape, d.labeled_cells)
        row_errors = error_positions.updated_row_errors()

        if self.VICINITY_FEATURE_GENERATOR == 'pdep' and 'vicinity' in self.FEATURE_GENERATORS:
            d.inv_vicinity_gpdeps = {}
            for order in self.VICINITY_ORDERS:
                vicinity_gpdeps = pdep.calc_all_gpdeps(d.vicinity_models, d.lhs_values_frequencies, shape, row_errors, order)
                d.inv_vicinity_gpdeps[order] = pdep.invert_and_sort_gpdeps(vicinity_gpdeps)

        if 'fd' in self.FEATURE_GENERATORS:
            # calculate FDs
            inputted_rows = list(d.labeled_tuples.keys())
            df_user_input = d.clean_dataframe.iloc[inputted_rows, :]  # careful, this is ground truth.
            df_clean_iterative = pdep.cleanest_version(d.dataframe, df_user_input)
            d.fds = pdep.mine_fds(df_clean_iterative, d.clean_dataframe)

            # calculate gpdeps
            shape = d.dataframe.shape
            error_positions = helpers.ErrorPositions(d.detected_cells, shape, d.labeled_cells)
            row_errors = error_positions.updated_row_errors()
            d.fd_counts_dict, lhs_values_frequencies = pdep.mine_fd_counts(d.dataframe, row_errors, d.fds)
            gpdeps = pdep.fd_calc_gpdeps(d.fd_counts_dict, lhs_values_frequencies, shape, row_errors)

            d.fd_inverted_gpdeps = {}
            for lhs in gpdeps:
                for rhs in gpdeps[lhs]:
                    if rhs not in d.fd_inverted_gpdeps:
                        d.fd_inverted_gpdeps[rhs] = {}
                    d.fd_inverted_gpdeps[rhs][lhs] = gpdeps[lhs][rhs]

            # normalize gpdeps per rhs
            for rhs in d.fd_inverted_gpdeps:
                norm_sum = 0
                for lhs, pdep_tuple in d.fd_inverted_gpdeps[rhs].items():
                    if pdep_tuple is not None:
                        norm_sum += pdep_tuple.gpdep
                if norm_sum > 0:
                    for lhs, pdep_tuple in d.fd_inverted_gpdeps[rhs].items():
                        if pdep_tuple is not None:
                            d.fd_inverted_gpdeps[rhs][lhs] = pdep.PdepTuple(pdep_tuple.pdep,
                                                                            pdep_tuple.gpdep,
                                                                            pdep_tuple.epdep,
                                                                            pdep_tuple.gpdep / norm_sum)

        if 'auto_instance' in self.FEATURE_GENERATORS and len(d.labeled_tuples) == self.LABELING_BUDGET:
            # simulate user input by reading labeled data from the typed dataframe
            inputted_rows = list(d.labeled_tuples.keys())
            typed_user_input = d.typed_clean_dataframe.iloc[inputted_rows, :]
            df_clean_subset = auto_instance.get_clean_table(d.typed_dataframe, d.detected_cells, typed_user_input)
            for i_col, col in enumerate(df_clean_subset.columns):
                imp = auto_instance.train_cleaning_model(df_clean_subset,
                                                   d.name,
                                                   label=i_col,
                                                   time_limit=self.TRAINING_TIME_LIMIT,
                                                   use_cache=self.AUTO_INSTANCE_CACHE_MODEL)
                if imp is not None:
                    d.imputer_models[i_col] = imp.predict_proba(d.typed_dataframe)
                else:
                    d.imputer_models[i_col] = None

    def generate_features(self, d, synchronous):
        """
        Use correctors to generate correction features.
        """
        ai_prompts: List[Tuple[Tuple[int, int], str, Union[str, None]]] = []
        process_args_list = [[d, cell, False] for cell in d.detected_cells]

        # generate all features but the llm-features
        if not synchronous:
            pool = multiprocessing.Pool()
            prompt_lists = pool.map(self._feature_generator_process, process_args_list)
            pool.close()
            for l in prompt_lists:
                ai_prompts.extend(l)
        else:
            for args in process_args_list:
                ai_prompts.extend(self._feature_generator_process(args))

        # generate llm-features
        if len(d.labeled_tuples) == self.LABELING_BUDGET:
            for error_cell, model_name, prompt in ai_prompts:
                correction, token_logprobs, top_logprobs = helpers.fetch_cached_llm(d.name, error_cell, prompt, model_name, d.error_fraction, d.version, d.error_class)
                correction_dicts = helpers.llm_response_to_corrections(correction, token_logprobs, top_logprobs)
                d.corrections.get(model_name)[error_cell] = correction_dicts

        if self.VERBOSE:
            print("User Features Generated.")

    def generate_inferred_features(self, d, synchronous):
        """
        Generate additional training data by using data from the dirty dataframe. This leverages the information about
        error positions, carefully avoiding additional training data that contains known errors.
        """

        error_positions = helpers.ErrorPositions(d.detected_cells, d.dataframe.shape, d.labeled_cells)
        row_errors = error_positions.updated_row_errors()

        # determine error-free rows to sample from.
        candidate_rows = [(row, len(cells)) for row, cells in row_errors.items() if len(cells) == 0]
        ranked_candidate_rows = sorted(candidate_rows, key=lambda x: x[1])

        if self.SYNTH_TUPLES > 0 and len(ranked_candidate_rows) > 0:
            # sample randomly to prevent sorted data messing up the sampling process.
            random.seed(0)
            if len(ranked_candidate_rows) <= self.SYNTH_TUPLES:
                synthetic_error_rows = random.sample([x[0] for x in ranked_candidate_rows], len(ranked_candidate_rows))
            else:
                synthetic_error_rows = random.sample([x[0] for x in ranked_candidate_rows[:self.SYNTH_TUPLES]], self.SYNTH_TUPLES)
            synthetic_error_cells = [(i, j) for i in synthetic_error_rows for j in range(d.dataframe.shape[1])]

            synth_args_list = [[d, cell, True] for cell in synthetic_error_cells]
            ai_prompts: List[Tuple[Tuple[int, int], str, Union[str, None]]] = []

            if not synchronous:
                pool = multiprocessing.Pool()
                prompt_lists = pool.map(self._feature_generator_process, synth_args_list)
                pool.close()
                for l in prompt_lists:
                    ai_prompts.extend(l)
            else:
                for args in synth_args_list:
                    ai_prompts.extend(self._feature_generator_process(args))

            # Stub to get llm_master to work in unsupervised setup.
            #
            # generate llm-features
            # for error_cell, model_name, prompt in ai_prompts:
            #     cache = helpers.fetch_cache(d.name,
            #                                 error_cell,
            #                                 model_name,
            #                                 d.error_fraction,
            #                                 d.version,
            #                                 d.error_class)
            #     if cache is not None:
            #         correction, token_logprobs, top_logprobs = cache
            #         correction_dicts = helpers.llm_response_to_corrections(correction, token_logprobs, top_logprobs)
            #         d.inferred_corrections.get(model_name)[error_cell] = correction_dicts

            if self.VERBOSE:
                print("Inferred Features Generated.")


    def binary_predict_corrections(self, d):
        """
        The ML problem as formulated in the Baran paper.
        """
        error_positions = helpers.ErrorPositions(d.detected_cells, d.dataframe.shape, d.labeled_cells)
        column_errors = error_positions.original_column_errors()
        pair_features = d.corrections.assemble_pair_features()
        synth_pair_features = d.inferred_corrections.assemble_pair_features()

        for j in column_errors:
            if d.corrections.et_valid_corrections_made(d.corrected_cells, j) > 0:  # ET model mentioned ground truth once in suggestions
                score = 0  # drop inferred_features to not distort correction classifier.

            else:  # evaluate synth tuples.
                score = ml_helpers.test_synth_data(d,
                                                   pair_features,
                                                   synth_pair_features,
                                                   self.CLASSIFICATION_MODEL,
                                                   j,
                                                   column_errors,
                                                   clean_on=self.TEST_SYNTH_DATA_DIRECTION)

            if score >= self.SYNTH_CLEANING_THRESHOLD:
                # now that we are certain about the synth data's usefulness, use additional training data.
                x_train, y_train, x_test, user_corrected_cells, error_correction_suggestions = ml_helpers.generate_train_test_data(
                    column_errors,
                    d.labeled_cells,
                    pair_features,
                    d.dataframe,
                    synth_pair_features,
                    j)
            else:  # score is below threshold, don't use additional training data
                x_train, y_train, x_test, user_corrected_cells, error_correction_suggestions = ml_helpers.generate_train_test_data(
                    column_errors,
                    d.labeled_cells,
                    pair_features,
                    d.dataframe,
                    {},
                    j)

            is_valid_problem, predicted_labels, predicted_probas = ml_helpers.handle_edge_cases(x_train, x_test, y_train)
            
            if is_valid_problem:
                if self.CLASSIFICATION_MODEL == "ABC" or sum(y_train) <= 2:
                    gs_clf = sklearn.ensemble.AdaBoostClassifier(n_estimators=100)
                    gs_clf.fit(x_train, y_train, )
                elif self.CLASSIFICATION_MODEL == "CV":
                    gs_clf = hpo.cross_validated_estimator(x_train, y_train)
                else:
                    raise ValueError('Unknown model.')

                predicted_labels = gs_clf.predict(x_test)
                predicted_probas = [x[1] for x in gs_clf.predict_proba(x_test)]

            ml_helpers.set_binary_cleaning_suggestions(predicted_labels, predicted_probas, x_test, error_correction_suggestions, d.corrected_cells)

        if self.LABELING_BUDGET == len(d.labeled_tuples) and self.DATASET_ANALYSIS:
            samples = {c: random.sample(column_errors[c], min(40, len(column_errors[c]))) for c in column_errors}
            normalized_dataset = d.name
            normalized_dataset = f'{d.name}_{d.error_class}_{d.error_fraction}'

            analysis = {
                    'dataset': normalized_dataset,
                    'error_stats': [{'column': c, 'errors': len(e)} for c,e in column_errors.items()],
                    'samples': [{'column': col, 'cell': c, 'error': d.dataframe.iloc[c], 'correction': d.clean_dataframe.iloc[c], 'correction_suggestion': d.corrected_cells.get(c, 'no corrections suggested')}
                                    for col in samples for c in samples[col]],
                    'correctors': [{'corrector': cor,
                                    'column': col,
                                    'cell': c,
                                    'error': d.dataframe.iloc[c],
                                    'correction': d.clean_dataframe.iloc[c],
                                    'correction_suggestions': d.corrections.correction_store[cor].get(c)} for cor in d.corrections.correction_store for col in samples for c in samples[col]]
                }

            with open(f'analysis/{normalized_dataset}.json', 'wt') as f:
                json.dump(analysis, f)

        if self.VERBOSE:
            print("{:.0f}% ({} / {}) of data errors are corrected.".format(
                100 * len(d.corrected_cells) / len(d.detected_cells),
                len(d.corrected_cells), len(d.detected_cells)))

    def clean_with_user_input(self, d):
        """
        User input ideally contains completely correct data. It should be leveraged for optimal cleaning
        performance.
        """
        if not self.CLEAN_WITH_USER_INPUT:
            return None
        for error_cell in d.detected_cells:
            if error_cell in d.labeled_cells:
                d.corrected_cells[error_cell] = d.labeled_cells[error_cell][1]

    def store_results(self, d):
        """
        This method stores the results.
        """
        ec_folder_path = os.path.join(d.results_folder, "error-correction")
        if not os.path.exists(ec_folder_path):
            os.mkdir(ec_folder_path)
        pickle.dump(d, open(os.path.join(ec_folder_path, "correction.dataset"), "wb"))

    def run(self, d, random_seed):
        """
        This method runs Mimir on an input dataset to correct data errors.
        """
        d = self.initialize_dataset(d)
        if len(d.detected_cells) == 0:
            raise ValueError('There are no errors in the data to correct.')
        if self.VERBOSE:
            text = f"Start Mimir To Correct Dataset {d.name}"
            print(f"{text}\n")
        self.initialize_models(d)

        while len(d.labeled_tuples) <= self.LABELING_BUDGET:
            self.prepare_augmented_models(d)
            self.generate_features(d, synchronous=True)
            self.generate_inferred_features(d, synchronous=True)
            self.binary_predict_corrections(d)
            self.clean_with_user_input(d)
            self.sample_tuple(d, random_seed=random_seed)
            self.label_with_ground_truth(d)
            self.update_models(d)

            if self.VERBOSE:
                p, r, f = d.get_data_cleaning_evaluation(d.corrected_cells)[-3:]
                print(
                    "Cleaning performance on {}:\nPrecision = {:.2f}\nRecall = {:.2f}\nF1 = {:.2f}\n".format(d.name, p, r,
                                                                                                           f))
        return d.corrected_cells


if __name__ == "__main__":
    # store results for detailed analysis
    dataset_analysis = True

    dataset_name = "151"
    error_class = 'simple_mcar'
    error_fraction = 5
    version = 1
    n_rows = 1000

    labeling_budget = 20
    synth_tuples = 100
    synth_cleaning_threshold = 0.9
    auto_instance_cache_model = True
    clean_with_user_input = True  # Careful: If set to False, d.corrected_cells will remain empty.
    gpdep_threshold = 0.3
    training_time_limit = 30
    feature_generators = ['auto_instance', 'fd', 'llm_correction', 'llm_master']
    #feature_generators = ['llm_correction']
    classification_model = "ABC"
    fd_feature = 'norm_gpdep'
    vicinity_orders = [1]
    n_best_pdeps = 3
    vicinity_feature_generator = "naive"
    pdep_features = ['pr']
    test_synth_data_direction = 'user_data'
    domain_model_threshold = 0.01

    # Set this parameter to keep runtimes low when debugging
    data = dataset.Dataset(dataset_name, error_fraction, version, error_class, n_rows)
    data.detected_cells = data.get_errors_dictionary()

    app = Cleaning(labeling_budget, classification_model, clean_with_user_input, feature_generators, vicinity_orders,
                     vicinity_feature_generator, auto_instance_cache_model, n_best_pdeps, training_time_limit,
                     synth_tuples, synth_cleaning_threshold, test_synth_data_direction, pdep_features, gpdep_threshold,
                     fd_feature, domain_model_threshold, dataset_analysis)
    app.VERBOSE = True
    seed = 0
    correction_dictionary = app.run(data, seed)
