import tensorflow as tf


def _activation_summary(x):
    """Helper to create summaries for activations.

    Creates a summary that provides a histogram of activations.
    Creates a summary that measures the sparsity of activations.

    Args:
        x: Tensor
    """

    tf.summary.histogram(x.op.name + '/activations', x)
    tf.summary.scalar(x.op.name + '/sparsity', tf.nn.zero_fraction(x))


def _weight_variable(name, shape, stddev, decay):
    var = tf.get_variable(name, shape,
                          initializer=tf.truncated_normal_initializer(
                              stddev=stddev, dtype=tf.float32),
                          dtype=tf.float32)

    weight_decay = tf.mul(tf.nn.l2_loss(var), decay, name='weight_loss')
    tf.add_to_collection('losses', weight_decay)
    return var


def _bias_variable(name, shape, constant):
    var = tf.get_variable(name, shape,
                          initializer=tf.constant_initializer(constant),
                          dtype=tf.float32)

    return var


# {
#   conv: [
#      {
#        output_channels: 64,
#        weights: { stddev, decay },
#        biases: { constant: 0.1 },
#        fields: { size: [5, 5], strides: [1, 1] },
#        max_pool: { size: [3, 3], strides: [2, 2] },
#     }
#   ],
#   local: [
#      {
#        output_channels: 1024,
#        weights: { stddev, decay },
#        biases: { constant: 0.1 },
#     }
#   ],
#   softmax_linear: {
#      output_channels: 10,
#      weights: { stddev, decay },
#      biases: { constant: 0.1 },
#   }
# }
def inference(data, network, keep_prob):
    output = data
    i = 1

    for layer in network['conv']:
        input_channels = output.get_shape()[3].value
        output_channels = layer['output_channels']

        weights_shape = (layer['fields']['size'] + [input_channels] +
                         [output_channels])

        strides = [1] + layer['fields']['strides'] + [1]

        with tf.variable_scope('conv_{}'.format(i)) as scope:

            weights = _weight_variable(
                name='weights',
                shape=weights_shape,
                stddev=layer['weights']['stddev'],
                decay=layer['weights']['decay'])

            biases = _bias_variable(
                name='biases',
                shape=[output_channels],
                constant=layer['biases']['constant'])

            output = tf.nn.conv2d(output, weights, strides, padding='SAME')
            output = tf.nn.bias_add(output, biases)
            output = tf.nn.relu(output, name=scope.name)
            _activation_summary(output)

        if 'max_pool' in layer:
            max_pool_size = [1] + layer['max_pool']['size'] + [1]
            max_pool_strides = [1] + layer['max_pool']['strides'] + [1]

            output = tf.nn.max_pool(output, max_pool_size, max_pool_strides,
                                    padding='SAME', name='pool_{}'.format(i))

        i += 1

    shape = output.get_shape().as_list()
    output = tf.reshape(output, [-1, shape[1] * shape[2] * shape[3]])

    for layer in network['fully_connected']:
        input_channels = output.get_shape()[1].value
        output_channels = layer['output_channels']

        with tf.variable_scope('fc_{}'.format(i)) as scope:

            weights = _weight_variable(
                name='weights',
                shape=[input_channels, output_channels],
                stddev=layer['weights']['stddev'],
                decay=layer['weights']['decay'])

            biases = _bias_variable(
                name='biases',
                shape=[output_channels],
                constant=layer['biases']['constant'])

            output = tf.matmul(output, weights) + biases
            output = tf.nn.relu(output, name=scope.name)
            _activation_summary(output)

        i += 1

    layer = network['softmax_linear']
    input_channels = output.get_shape()[1].value
    output_channels = layer['output_channels']

    # Apply dropout.
    output = tf.nn.dropout(output, keep_prob)

    with tf.variable_scope('softmax_linear') as scope:

        weights = _weight_variable(
            name='weights',
            shape=[input_channels, output_channels],
            stddev=layer['weights']['stddev'],
            decay=layer['weights']['decay'])

        biases = _bias_variable(
            name='biases',
            shape=[output_channels],
            constant=layer['biases']['constant'])

        output = tf.matmul(output, weights)
        output = tf.add(output, biases, name=scope.name)
        _activation_summary(output)

    return output
