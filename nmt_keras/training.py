# -*- coding: utf-8 -*-
from __future__ import print_function
from nmt_keras.build_callbacks import buildCallbacks, buildCallbacksMultiDataSet
import jsonpickle
from nmt_keras.model_zoo import TranslationModel
from keras_wrapper.extra.read_write import dict2pkl
from keras_wrapper.dataset import loadDataset, saveDataset
from keras_wrapper.cnn_model import updateModel,updateModelMultiway
from data_engine.prepare_data import build_dataset, update_dataset_from_file, build_dataset_multilanguage
from six import iteritems
from timeit import default_timer as timer
import logging
import json
import nmt_keras

logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] %(message)s', datefmt='%d/%m/%Y %H:%M:%S')
logger = logging.getLogger(__name__)


def train_model(params, load_dataset=None):
    """
    Training function.

    Sets the training parameters from params.

    Build or loads the model and launches the training.

    :param dict params: Dictionary of network hyperparameters.
    :param str load_dataset: Load dataset from file or build it from the parameters.
    :return: None
    """

    if params['RELOAD'] > 0:
        logger.info('Resuming training.')
        # Load data
        if load_dataset is None:
            if params['REBUILD_DATASET']:
                logger.info('Rebuilding dataset.')
                if params['MULTILANGUAGE'] == 0:
                    dataset = build_dataset(params)
                else:
                    datasets = build_dataset_multilanguage(params)
            else:
                logger.info('Updating dataset.')
                dataset = loadDataset(
                    params['DATASET_STORE_PATH'] + '/Dataset_' + params['DATASET_NAME'] + '_' + params['SRC_LAN'] +
                    params['TRG_LAN'] + '.pkl')

                epoch_offset = 0 if dataset.len_train == 0 else int(
                    params['RELOAD'] * params['BATCH_SIZE'] / dataset.len_train)
                params['EPOCH_OFFSET'] = params['RELOAD'] if params['RELOAD_EPOCH'] else epoch_offset

                for split, filename in iteritems(params['TEXT_FILES']):
                    dataset = update_dataset_from_file(dataset,
                                                       params['DATA_ROOT_PATH'] + '/' +
                                                       filename +
                                                       params['SRC_LAN'],
                                                       params,
                                                       splits=list([split]),
                                                       output_text_filename=params['DATA_ROOT_PATH'] +
                                                       '/' + filename +
                                                       params['TRG_LAN'],
                                                       remove_outputs=False,
                                                       compute_state_below=True,
                                                       recompute_references=True)
                    dataset.name = params['DATASET_NAME'] + \
                        '_' + params['SRC_LAN'] + params['TRG_LAN']
                saveDataset(dataset, params['DATASET_STORE_PATH'])

        else:
            logger.info('Reloading and using dataset.')
            dataset = loadDataset(load_dataset)
    else:
        # Load data
        if load_dataset is None:
            if params['MULTILANGUAGE'] == 0:
                dataset = build_dataset(params)
            else:
                datasets = build_dataset_multilanguage(params)
        else:
            dataset = loadDataset(load_dataset)
    #
    #
    # MODIFICAR EL TAMAÑO DEL VOCABULARIO
    # ENCONTRAR UN PUNTO MEDIO
    #
    if params['MULTILANGUAGE'] > 0:
        params['INPUT_VOCABULARY_SIZE'] = max(
            datasets[0].vocabulary_len[params['INPUTS_IDS_DATASET'][0]], datasets[1].vocabulary_len[params['INPUTS_IDS_DATASET'][0]])
        params['OUTPUT_VOCABULARY_SIZE'] = datasets[0].vocabulary_len[params['OUTPUTS_IDS_DATASET'][0]]
        params['OUTPUT_VOCABULARY_SIZE_2'] = datasets[1].vocabulary_len[params['OUTPUTS_IDS_DATASET'][0]]
    else:
        params['INPUT_VOCABULARY_SIZE'] = dataset.vocabulary_len[params['INPUTS_IDS_DATASET'][0]]
        params['OUTPUT_VOCABULARY_SIZE'] = dataset.vocabulary_len[params['OUTPUTS_IDS_DATASET'][0]]

    # Build model
    set_optimizer = True if params['RELOAD'] == 0 else False
    clear_dirs = True if params['RELOAD'] == 0 else False

    # build new model
    # CONSTRUIR NUESTRO PROPIO MODELO

    if params['MULTILANGUAGE'] > 0:
        nmt_model = TranslationModel(params,
                                     model_type="ParalelDecoder",
                                     verbose=params['VERBOSE'],
                                     model_name=params['MODEL_NAME'],
                                     # modify the vocabulary!!!
                                     vocabularies=datasets[0].vocabulary,
                                     store_path=params['STORE_PATH'],
                                     set_optimizer=set_optimizer,
                                     clear_dirs=clear_dirs)
    else:
        nmt_model = TranslationModel(params,
                                     model_type=params['MODEL_TYPE'],
                                     verbose=params['VERBOSE'],
                                     model_name=params['MODEL_NAME'],
                                     vocabularies=dataset.vocabulary,
                                     store_path=params['STORE_PATH'],
                                     set_optimizer=set_optimizer,
                                     clear_dirs=clear_dirs)
    # Define the inputs and outputs mapping from our Dataset instance to our model
    inputMapping = dict()
    for i, id_in in enumerate(params['INPUTS_IDS_DATASET']):
        pos_source = datasets[0].ids_inputs.index(id_in)
        id_dest = nmt_model.ids_inputs[i]
        inputMapping[id_dest] = pos_source
    nmt_model.setInputsMapping(inputMapping)
    
    outputMapping = dict()
    for i, id_out in enumerate(params['OUTPUTS_IDS_DATASET']):
        pos_target = datasets[0].ids_outputs.index(id_out)
        id_dest = nmt_model.ids_outputs[i]
        outputMapping[id_dest] = pos_target
    nmt_model.setOutputsMapping(outputMapping)
    print("Outputs: ", outputMapping)
    # print(jsonpickle.encode(dataset))
    print("____________________________________________")
    print(datasets[0])
    print("____________________________________________")
    print(datasets[1])
    if params['RELOAD'] > 0:
        if params['MULTILANGUAGE'] != 1:
            nmt_model = updateModel(nmt_model, params['STORE_PATH'], params['RELOAD'], reload_epoch=params['RELOAD_EPOCH'])
        else:
            nmt_model = updateModelMultiway(nmt_model, params['STORE_PATH'], params['RELOAD'], reload_epoch=params['RELOAD_EPOCH'])
        nmt_model.setParams(params)
        nmt_model.setOptimizer()
        if params.get('EPOCH_OFFSET') is None:
            params['EPOCH_OFFSET'] = params['RELOAD'] if params['RELOAD_EPOCH'] else \
                int(params['RELOAD'] *
                    params['BATCH_SIZE'] / dataset.len_train)
    # Store configuration as pkl
    dict2pkl(params, params['STORE_PATH'] + '/config')

    # Callbacks
    if params['MULTILANGUAGE'] != 1:
        callbacks = buildCallbacks(params, nmt_model, dataset)
        training_params = {
            'n_epochs': params['MAX_EPOCH'],
            'batch_size': params['BATCH_SIZE'],
            'homogeneous_batches': params['HOMOGENEOUS_BATCHES'],
            'maxlen': params['MAX_OUTPUT_TEXT_LEN'],
            'joint_batches': params['JOINT_BATCHES'],
            # LR decay parameters
            'lr_decay': params.get('LR_DECAY', None),
            'initial_lr': params.get('LR', 1.0),
            'reduce_each_epochs': params.get('LR_REDUCE_EACH_EPOCHS', True),
            'start_reduction_on_epoch': params.get('LR_START_REDUCTION_ON_EPOCH', 0),
            'lr_gamma': params.get('LR_GAMMA', 0.9),
            'lr_reducer_type': params.get('LR_REDUCER_TYPE', 'linear'),
            'lr_reducer_exp_base': params.get('LR_REDUCER_EXP_BASE', 0),
            'lr_half_life': params.get('LR_HALF_LIFE', 50000),
            'lr_warmup_exp': params.get('WARMUP_EXP', -1.5),
            'min_lr': params.get('MIN_LR', 1e-9),
            'epochs_for_save': params['EPOCHS_FOR_SAVE'],
            'verbose': params['VERBOSE'],
            'eval_on_sets': params['EVAL_ON_SETS_KERAS'],
            'n_parallel_loaders': params['PARALLEL_LOADERS'],
            'extra_callbacks': callback,
            'reload_epoch': params['RELOAD'],
            'epoch_offset': params.get('EPOCH_OFFSET', 0),
            'data_augmentation': params['DATA_AUGMENTATION'],
            # early stopping parameters
            'patience': params.get('PATIENCE', 0),
            'metric_check': params.get('STOP_METRIC', None) if params.get('EARLY_STOP', False) else None,
            'min_delta': params.get('MIN_DELTA', 0.),
            'eval_on_epochs': params.get('EVAL_EACH_EPOCHS', True),
            'each_n_epochs': params.get('EVAL_EACH', 1),
            'start_eval_on_epoch': params.get('START_EVAL_ON_EPOCH', 0),
            'tensorboard': params.get('TENSORBOARD', False),
            'n_gpus': params.get('N_GPUS', 1),
            'tensorboard_params': {'log_dir': params.get('LOG_DIR', 'tensorboard_logs'),
                                   'histogram_freq': params.get('HISTOGRAM_FREQ', 0),
                                   'batch_size': params.get('TENSORBOARD_BATCH_SIZE', params['BATCH_SIZE']),
                                   'write_graph': params.get('WRITE_GRAPH', True),
                                   'write_grads': params.get('WRITE_GRADS', False),
                                   'write_images': params.get('WRITE_IMAGES', False),
                                   'embeddings_freq': params.get('EMBEDDINGS_FREQ', 0),
                                   'embeddings_layer_names': params.get('EMBEDDINGS_LAYER_NAMES', None),
                                   'embeddings_metadata': params.get('EMBEDDINGS_METADATA', None),
                                   'label_word_embeddings_with_vocab': params.get(
                'LABEL_WORD_EMBEDDINGS_WITH_VOCAB', False),
                'word_embeddings_labels': params.get('WORD_EMBEDDINGS_LABELS', None),
            }
        }
    else:
        callbacks = buildCallbacksMultiDataSet(params, nmt_model, datasets)
        multi_training_params = []
        for callback in callbacks:
            training_params = {
                'n_epochs': params['MAX_EPOCH'],
                'batch_size': params['BATCH_SIZE'],
                'homogeneous_batches': params['HOMOGENEOUS_BATCHES'],
                'maxlen': params['MAX_OUTPUT_TEXT_LEN'],
                'joint_batches': params['JOINT_BATCHES'],
                # LR decay parameters
                'lr_decay': params.get('LR_DECAY', None),
                'initial_lr': params.get('LR', 1.0),
                'reduce_each_epochs': params.get('LR_REDUCE_EACH_EPOCHS', True),
                'start_reduction_on_epoch': params.get('LR_START_REDUCTION_ON_EPOCH', 0),
                'lr_gamma': params.get('LR_GAMMA', 0.9),
                'lr_reducer_type': params.get('LR_REDUCER_TYPE', 'linear'),
                'lr_reducer_exp_base': params.get('LR_REDUCER_EXP_BASE', 0),
                'lr_half_life': params.get('LR_HALF_LIFE', 50000),
                'lr_warmup_exp': params.get('WARMUP_EXP', -1.5),
                'min_lr': params.get('MIN_LR', 1e-9),
                'epochs_for_save': params['EPOCHS_FOR_SAVE'],
                'verbose': params['VERBOSE'],
                'eval_on_sets': params['EVAL_ON_SETS_KERAS'],
                'n_parallel_loaders': params['PARALLEL_LOADERS'],
                'extra_callbacks': callback,
                'reload_epoch': params['RELOAD'],
                'epoch_offset': params.get('EPOCH_OFFSET', 0),
                'data_augmentation': params['DATA_AUGMENTATION'],
                # early stopping parameters
                'patience': params.get('PATIENCE', 0),
                'metric_check': params.get('STOP_METRIC', None) if params.get('EARLY_STOP', False) else None,
                'min_delta': params.get('MIN_DELTA', 0.),
                'eval_on_epochs': params.get('EVAL_EACH_EPOCHS', True),
                'each_n_epochs': params.get('EVAL_EACH', 1),
                'start_eval_on_epoch': params.get('START_EVAL_ON_EPOCH', 0),
                'tensorboard': params.get('TENSORBOARD', False),
                'n_gpus': params.get('N_GPUS', 1),
                'tensorboard_params': {'log_dir': params.get('LOG_DIR', 'tensorboard_logs'),
                                       'histogram_freq': params.get('HISTOGRAM_FREQ', 0),
                                       'batch_size': params.get('TENSORBOARD_BATCH_SIZE', params['BATCH_SIZE']),
                                       'write_graph': params.get('WRITE_GRAPH', True),
                                       'write_grads': params.get('WRITE_GRADS', False),
                                       'write_images': params.get('WRITE_IMAGES', False),
                                       'embeddings_freq': params.get('EMBEDDINGS_FREQ', 0),
                                       'embeddings_layer_names': params.get('EMBEDDINGS_LAYER_NAMES', None),
                                       'embeddings_metadata': params.get('EMBEDDINGS_METADATA', None),
                                       'label_word_embeddings_with_vocab': params.get(
                    'LABEL_WORD_EMBEDDINGS_WITH_VOCAB', False),
                    'word_embeddings_labels': params.get('WORD_EMBEDDINGS_LABELS', None),
                }
            }
            multi_training_params.append(training_params)    # Training
    total_start_time = timer()

    logger.debug('Starting training!')

    if params['MULTILANGUAGE'] != 1:
        nmt_model.trainNet(dataset, training_params)
    else:
        nmt_model.trainNet(datasets, multi_training_params)

    total_end_time = timer()
    time_difference = total_end_time - total_start_time
    logger.info('In total is {0:.2f}s = {1:.2f}m'.format(
        time_difference, time_difference / 60.0))
