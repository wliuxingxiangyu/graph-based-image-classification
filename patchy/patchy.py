import os
import sys
import json

import tensorflow as tf

from data import DataSet, Record, datasets
from data import iterator, read_tfrecord, write_tfrecord
from grapher import graphers

from .helper.labeling import labelings, scanline
from .helper.neighborhood_assembly import neighborhood_assemblies as neighb,\
                                          neighborhoods_weights_to_root
from .helper.node_sequence import node_sequence


DATA_DIR = '/tmp/patchy_san_data'
FORCE_WRITE = False
WRITE_NUM_EPOCHS = 1
DISTORT_INPUTS = False

NUM_NODES = 100
NODE_STRIDE = 1
NEIGHBORHOOD_SIZE = 9

INFO_FILENAME = 'info.json'
TRAIN_FILENAME = 'train.tfrecords'
TRAIN_INFO_FILENAME = 'train_info.json'
TRAIN_EVAL_FILENAME = 'train_eval.tfrecords'
TRAIN_EVAL_INFO_FILENAME = 'train_eval_info.json'
EVAL_FILENAME = 'eval.tfrecords'
EVAL_INFO_FILENAME = 'eval_info.json'


class PatchySan(DataSet):

    def __init__(self, dataset, grapher, data_dir=DATA_DIR,
                 force_write=FORCE_WRITE, write_num_epochs=WRITE_NUM_EPOCHS,
                 distort_inputs=DISTORT_INPUTS, node_labeling=None,
                 num_nodes=NUM_NODES, node_stride=NODE_STRIDE,
                 neighborhood_assembly=None,
                 neighborhood_size=NEIGHBORHOOD_SIZE):

        node_labeling = scanline if node_labeling is None else node_labeling
        neighborhood_assembly = neighborhoods_weights_to_root if\
            neighborhood_assembly is None else neighborhood_assembly

        self._dataset = dataset
        self._grapher = grapher
        self._num_nodes = num_nodes
        self._neighborhood_size = neighborhood_size
        self._distort_inputs = distort_inputs

        super().__init__(data_dir)

        if tf.gfile.Exists(data_dir) and force_write:
            tf.gfile.DeleteRecursively(data_dir)

        tf.gfile.MakeDirs(data_dir)

        info_file = os.path.join(data_dir, INFO_FILENAME)

        if not tf.gfile.Exists(info_file) or force_write:
            with open(info_file, 'w') as f:
                json.dump({'max_num_epochs': write_num_epochs,
                           'distort_inputs': distort_inputs,
                           'node_labeling': node_labeling.__name__,
                           'num_nodes': num_nodes,
                           'num_node_channels': grapher.num_node_channels,
                           'node_stride': node_stride,
                           'neighborhood_assembly':
                           neighborhood_assembly.__name__,
                           'neighborhood_size': neighborhood_size,
                           'num_edge_channels': grapher.num_edge_channels}, f)

        train_file = os.path.join(data_dir, TRAIN_FILENAME)
        train_info_file = os.path.join(data_dir, TRAIN_INFO_FILENAME)

        if not tf.gfile.Exists(train_file):
            _write(dataset, grapher, False, train_file, train_info_file,
                   write_num_epochs, distort_inputs, True, node_labeling,
                   num_nodes, node_stride, neighborhood_assembly,
                   neighborhood_size)

        eval_file = os.path.join(data_dir, EVAL_FILENAME)
        eval_info_file = os.path.join(data_dir, EVAL_INFO_FILENAME)

        if not tf.gfile.Exists(eval_file):
            _write(dataset, grapher, True, eval_file, eval_info_file,
                   1, distort_inputs, False, node_labeling, num_nodes,
                   node_stride, neighborhood_assembly, neighborhood_size)

        train_eval_file = os.path.join(data_dir, TRAIN_EVAL_FILENAME)
        train_eval_info_file = os.path.join(data_dir, TRAIN_EVAL_INFO_FILENAME)

        if distort_inputs and not tf.gfile.Exists(train_eval_file):
            _write(dataset, grapher, False, train_eval_file,
                   train_eval_info_file, 1, distort_inputs, False,
                   node_labeling, num_nodes, node_stride,
                   neighborhood_assembly, neighborhood_size)

    @classmethod
    def create(cls, config):
        """Static constructor to create a PatchySan dataset based on a json
        object.

        Args:
            config: A configuration object with sensible defaults for
              missing values.

        Returns:
            A PatchySan dataset.
        """

        dataset_config = config['dataset']
        grapher_config = config['grapher']

        return cls(datasets[dataset_config['name']].create(dataset_config),
                   graphers[grapher_config['name']].create(grapher_config),
                   config.get('data_dir', DATA_DIR),
                   config.get('force_write', FORCE_WRITE),
                   config.get('write_num_epochs', WRITE_NUM_EPOCHS),
                   config.get('distort_inputs', DISTORT_INPUTS),
                   labelings.get(config.get('node_labeling')),
                   config.get('num_nodes', NUM_NODES),
                   config.get('node_stride', NODE_STRIDE),
                   neighb.get(config.get('neighborhood_assembly')),
                   config.get('neighborhood_size', NEIGHBORHOOD_SIZE))

    @property
    def train_filenames(self):
        return [os.path.join(self.data_dir, TRAIN_FILENAME)]

    @property
    def eval_filenames(self):
        return [os.path.join(self.data_dir, EVAL_FILENAME)]

    @property
    def train_eval_filenames(self):
        if self._distort_inputs:
            return [os.path.join(self.data_dir, TRAIN_EVAL_FILENAME)]
        else:
            return [os.path.join(self.data_dir, TRAIN_FILENAME)]

    @property
    def labels(self):
        return self._dataset.labels

    @property
    def num_examples_per_epoch_for_train(self):
        with open(os.path.join(self._data_dir, TRAIN_INFO_FILENAME), 'r') as f:
            count = json.load(f)['count']
            return min(count, self._dataset.num_examples_per_epoch_for_train)

    @property
    def num_examples_per_epoch_for_eval(self):
        with open(os.path.join(self._data_dir, EVAL_INFO_FILENAME), 'r') as f:
            count = json.load(f)['count']
            return min(count, self._dataset.num_examples_per_epoch_for_eval)

    @property
    def num_examples_per_epoch_for_train_eval(self):
        if self._distort_inputs:
            filename = os.path.join(self._data_dir, TRAIN_EVAL_INFO_FILENAME)
            with open(filename, 'r') as f:
                count = json.load(f)['count']
                return min(count,
                           self._dataset.num_examples_per_epoch_for_train_eval)
        else:
            return self._dataset.num_examples_per_epoch_for_train

    def read(self, filename_queue):
        data, label = read_tfrecord(
            filename_queue,
            {'nodes': [-1, self._grapher.num_node_channels],
             'neighborhood': [self._num_nodes, self._neighborhood_size]})

        nodes = data['nodes']

        # Convert the neighborhood to a feature map.
        def _map_features(node):
            i = tf.maximum(node, 0)
            positive = tf.strided_slice(nodes, [i], [i+1], [1])
            negative = tf.zeros([1, self._grapher.num_node_channels])

            return tf.where(i < 0, negative, positive)

        data = tf.reshape(data['neighborhood'], [-1])
        data = tf.cast(data, tf.int32)
        data = tf.map_fn(_map_features, data, dtype=tf.float32)
        shape = [self._num_nodes, self._neighborhood_size,
                 self._grapher.num_node_channels]
        data = tf.reshape(data, shape)

        return Record(data, shape, label)


def _write(dataset, grapher, eval_data, tfrecord_file, info_file,
           write_num_epochs, distort_inputs, shuffle,
           node_labeling, num_nodes, node_stride, neighborhood_assembly,
           neighborhood_size):

    writer = tf.python_io.TFRecordWriter(tfrecord_file)

    iterate = iterator(dataset, eval_data, distort_inputs=distort_inputs,
                       num_epochs=write_num_epochs, shuffle=shuffle)

    def _before(image, label):
        nodes, adjacencies = grapher.create_graph(image)

        # Only take the first adjacency matrix.
        count = tf.shape(adjacencies)[0]
        adjacency = tf.strided_slice(
            adjacencies, [0, 0, 0], [count, count, 1], [1, 1, 1])
        adjacency = tf.squeeze(adjacency, axis=2)
        sequence = node_labeling(adjacency)
        sequence = node_sequence(sequence, num_nodes, node_stride)
        neighborhood = neighborhood_assembly(adjacency, sequence,
                                             neighborhood_size)

        return [nodes, neighborhood, label]

    def _each(output, index, last_index):
        write_tfrecord(writer,
                       {'nodes': output[0], 'neighborhood': output[1]},
                       output[2])

        sys.stdout.write(
            '\r>> Saving graphs to {} {:.1f}%'
            .format(tfrecord_file, 100.0 * index / last_index))
        sys.stdout.flush()

    def _done(index, last_index):
        print('')
        print('Successfully saved {} graphs to {}.'
              .format(index, tfrecord_file))

        with open(info_file, 'w') as f:
            json.dump({'count': index}, f)

    iterate(_each, _before, _done)
