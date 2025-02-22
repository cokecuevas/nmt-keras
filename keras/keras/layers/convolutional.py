# -*- coding: utf-8 -*-
"""Convolutional layers.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from .. import backend as K
from .. import activations
from .. import initializers
from .. import regularizers
from .. import constraints
from ..engine.base_layer import Layer
from ..engine.base_layer import InputSpec
from ..utils import conv_utils
from ..utils.generic_utils import transpose_shape
from ..legacy import interfaces

# imports for backwards namespace compatibility
from .pooling import AveragePooling1D
from .pooling import AveragePooling2D
from .pooling import AveragePooling3D
from .pooling import MaxPooling1D
from .pooling import MaxPooling2D
from .pooling import MaxPooling3D

from ..legacy.layers import AtrousConvolution1D
from ..legacy.layers import AtrousConvolution2D


class ClassActivationMapping(Layer):
    # TODO: Test this layer
    """Class Activation Mapping computation used in GAP networks.

    # Arguments
        weights_shape: Set of weights shapes
        weights: Set of weights (numpy.array) already learned that connect a
            GAP (global average pooling) layer with a Dense layer.

    # Input shape
        Arbitrary. Use the keyword argument `input_shape`
        (tuple of integers, does not include the samples axis)
        when using this layer as the first layer in a model.

    # Output shape
        Same shape as input.

    # References
        - [Learning Deep Features for Discriminative Localization](https://arxiv.org/abs/1512.04150)
    """

    def __init__(self, weights_shape, weights=None, **kwargs):
        self.weights_shape = weights_shape
        self.initial_weights = [weights]
        self.init = initializations.get('uniform', dim_ordering='th')
        self.input_spec = [InputSpec(ndim=4)]
        super(ClassActivationMapping, self).__init__(**kwargs)

    def build(self, input_shape):
        self.W = self.init(self.weights_shape,
                           name='{}_W'.format(self.name))
        self.trainable_weights = [self.W]

        # initialize weights
        if (self.initial_weights[0] is not None):
            self.set_weights(self.initial_weights)

    def call(self, x, mask=None):
        '''
        # Formulation
            The original CAM formulation from [1] is as follows:

                CAM(x,y,c) = ∑_k w_k(c) * f_k(x,y),

            where CAM(x,y,c) is the class activation map of class 'c'
            at pixel (x,y), w_k is the weight (self.W) of the k-th kernel
            learned on the Dense layer after GAP, and f_k is the feature
            activation at pixel (x,y) produced by the deep convolution layers
            applied before the GAP layer.
        '''
        x = K.permute_dimensions(x, (0, 2, 3, 1))
        x = K.dot(x, self.W)
        x = K.permute_dimensions(x, (0, 3, 1, 2))  # (batch_size, n_classes, x, y)
        return x

    def get_output_shape_for(self, input_shape):
        return tuple([input_shape[0]] + [self.weights_shape[1]] + list(input_shape[2:]))

    def get_config(self):
        config = {'weights_shape': self.weights_shape}
        base_config = super(ClassActivationMapping, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))


class _Conv(Layer):
    """Abstract nD convolution layer (private, used as implementation base).

    This layer creates a convolution kernel that is convolved
    with the layer input to produce a tensor of outputs.
    If `use_bias` is True, a bias vector is created and added to the outputs.
    Finally, if `activation` is not `None`,
    it is applied to the outputs as well.

    # Arguments
        rank: An integer, the rank of the convolution,
            e.g. "2" for 2D convolution.
        filters: Integer, the dimensionality of the output space
            (i.e. the number of output filters in the convolution).
        kernel_size: An integer or tuple/list of n integers, specifying the
            dimensions of the convolution window.
        strides: An integer or tuple/list of n integers,
            specifying the strides of the convolution.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: One of `"valid"` or `"same"` (case-insensitive).
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, ..., channels)` while `"channels_first"` corresponds to
            inputs with shape `(batch, channels, ...)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
        dilation_rate: An integer or tuple/list of n integers, specifying
            the dilation rate to use for dilated convolution.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any `strides` value != 1.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        kernel_initializer: Initializer for the `kernel` weights matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        kernel_regularizer: Regularizer function applied to
            the `kernel` weights matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its "activation").
            (see [regularizer](../regularizers.md)).
        kernel_constraint: Constraint function applied to the kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).
    """

    def __init__(self, rank,
                 filters,
                 kernel_size,
                 strides=1,
                 padding='valid',
                 data_format=None,
                 dilation_rate=1,
                 activation=None,
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 kernel_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(_Conv, self).__init__(**kwargs)
        self.rank = rank
        self.filters = filters
        self.kernel_size = conv_utils.normalize_tuple(kernel_size, rank,
                                                      'kernel_size')
        self.strides = conv_utils.normalize_tuple(strides, rank, 'strides')
        self.padding = conv_utils.normalize_padding(padding)
        self.data_format = K.normalize_data_format(data_format)
        self.dilation_rate = conv_utils.normalize_tuple(dilation_rate, rank,
                                                        'dilation_rate')
        self.activation = activations.get(activation)
        self.use_bias = use_bias
        self.kernel_initializer = initializers.get(kernel_initializer)
        self.bias_initializer = initializers.get(bias_initializer)
        self.kernel_regularizer = regularizers.get(kernel_regularizer)
        self.bias_regularizer = regularizers.get(bias_regularizer)
        self.activity_regularizer = regularizers.get(activity_regularizer)
        self.kernel_constraint = constraints.get(kernel_constraint)
        self.bias_constraint = constraints.get(bias_constraint)
        self.input_spec = InputSpec(ndim=self.rank + 2)

    def build(self, input_shape):
        if self.data_format == 'channels_first':
            channel_axis = 1
        else:
            channel_axis = -1
        if input_shape[channel_axis] is None:
            raise ValueError('The channel dimension of the inputs '
                             'should be defined. Found `None`.')
        input_dim = input_shape[channel_axis]
        kernel_shape = self.kernel_size + (input_dim, self.filters)

        self.kernel = self.add_weight(shape=kernel_shape,
                                      initializer=self.kernel_initializer,
                                      name='kernel',
                                      regularizer=self.kernel_regularizer,
                                      constraint=self.kernel_constraint)
        if self.use_bias:
            self.bias = self.add_weight(shape=(self.filters,),
                                        initializer=self.bias_initializer,
                                        name='bias',
                                        regularizer=self.bias_regularizer,
                                        constraint=self.bias_constraint)
        else:
            self.bias = None
        # Set input spec.
        self.input_spec = InputSpec(ndim=self.rank + 2,
                                    axes={channel_axis: input_dim})
        self.built = True

    def call(self, inputs):
        if self.rank == 1:
            outputs = K.conv1d(
                inputs,
                self.kernel,
                strides=self.strides[0],
                padding=self.padding,
                data_format=self.data_format,
                dilation_rate=self.dilation_rate[0])
        if self.rank == 2:
            outputs = K.conv2d(
                inputs,
                self.kernel,
                strides=self.strides,
                padding=self.padding,
                data_format=self.data_format,
                dilation_rate=self.dilation_rate)
        if self.rank == 3:
            outputs = K.conv3d(
                inputs,
                self.kernel,
                strides=self.strides,
                padding=self.padding,
                data_format=self.data_format,
                dilation_rate=self.dilation_rate)

        if self.use_bias:
            outputs = K.bias_add(
                outputs,
                self.bias,
                data_format=self.data_format)

        if self.activation is not None:
            return self.activation(outputs)
        return outputs

    def compute_output_shape(self, input_shape):
        if self.data_format == 'channels_last':
            space = input_shape[1:-1]
        elif self.data_format == 'channels_first':
            space = input_shape[2:]
        new_space = []
        for i in range(len(space)):
            new_dim = conv_utils.conv_output_length(
                space[i],
                self.kernel_size[i],
                padding=self.padding,
                stride=self.strides[i],
                dilation=self.dilation_rate[i])
            new_space.append(new_dim)
        if self.data_format == 'channels_last':
            return (input_shape[0],) + tuple(new_space) + (self.filters,)
        elif self.data_format == 'channels_first':
            return (input_shape[0], self.filters) + tuple(new_space)

    def get_config(self):
        config = {
            'rank': self.rank,
            'filters': self.filters,
            'kernel_size': self.kernel_size,
            'strides': self.strides,
            'padding': self.padding,
            'data_format': self.data_format,
            'dilation_rate': self.dilation_rate,
            'activation': activations.serialize(self.activation),
            'use_bias': self.use_bias,
            'kernel_initializer': initializers.serialize(self.kernel_initializer),
            'bias_initializer': initializers.serialize(self.bias_initializer),
            'kernel_regularizer': regularizers.serialize(self.kernel_regularizer),
            'bias_regularizer': regularizers.serialize(self.bias_regularizer),
            'activity_regularizer':
                regularizers.serialize(self.activity_regularizer),
            'kernel_constraint': constraints.serialize(self.kernel_constraint),
            'bias_constraint': constraints.serialize(self.bias_constraint)
        }
        base_config = super(_Conv, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))

    def set_lr_multipliers(self, W_learning_rate_multiplier, b_learning_rate_multiplier):
        self.W_learning_rate_multiplier = W_learning_rate_multiplier
        self.b_learning_rate_multiplier = b_learning_rate_multiplier
        self.learning_rate_multipliers = [self.W_learning_rate_multiplier,
                                          self.b_learning_rate_multiplier]


class Conv1D(_Conv):
    """1D convolution layer (e.g. temporal convolution).

    This layer creates a convolution kernel that is convolved
    with the layer input over a single spatial (or temporal) dimension
    to produce a tensor of outputs.
    If `use_bias` is True, a bias vector is created and added to the outputs.
    Finally, if `activation` is not `None`,
    it is applied to the outputs as well.

    When using this layer as the first layer in a model,
    provide an `input_shape` argument (tuple of integers or `None`, does not
    include the batch axis), e.g. `input_shape=(10, 128)` for time series
    sequences of 10 time steps with 128 features per step in
    `data_format="channels_last"`, or `(None, 128)` for variable-length
    sequences with 128 features per step.

    # Arguments
        filters: Integer, the dimensionality of the output space
            (i.e. the number of output filters in the convolution).
        kernel_size: An integer or tuple/list of a single integer,
            specifying the length of the 1D convolution window.
        strides: An integer or tuple/list of a single integer,
            specifying the stride length of the convolution.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: One of `"valid"`, `"causal"` or `"same"` (case-insensitive).
            `"valid"` means "no padding".
            `"same"` results in padding the input such that
            the output has the same length as the original input.
            `"causal"` results in causal (dilated) convolutions,
            e.g. `output[t]` does not depend on `input[t + 1:]`.
            A zero padding is used such that
            the output has the same length as the original input.
            Useful when modeling temporal data where the model
            should not violate the temporal order. See
            [WaveNet: A Generative Model for Raw Audio, section 2.1](
            https://arxiv.org/abs/1609.03499).
        data_format: A string,
            one of `"channels_last"` (default) or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, steps, channels)`
            (default format for temporal data in Keras)
            while `"channels_first"` corresponds to inputs
            with shape `(batch, channels, steps)`.
        dilation_rate: an integer or tuple/list of a single integer, specifying
            the dilation rate to use for dilated convolution.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any `strides` value != 1.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        kernel_initializer: Initializer for the `kernel` weights matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        kernel_regularizer: Regularizer function applied to
            the `kernel` weights matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its "activation").
            (see [regularizer](../regularizers.md)).
        kernel_constraint: Constraint function applied to the kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).

    # Input shape
        3D tensor with shape: `(batch, steps, channels)`

    # Output shape
        3D tensor with shape: `(batch, new_steps, filters)`
        `steps` value might have changed due to padding or strides.
    """

    @interfaces.legacy_conv1d_support
    def __init__(self, filters,
                 kernel_size,
                 strides=1,
                 padding='valid',
                 data_format='channels_last',
                 dilation_rate=1,
                 activation=None,
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 kernel_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        if padding == 'causal':
            if data_format != 'channels_last':
                raise ValueError('When using causal padding in `Conv1D`, '
                                 '`data_format` must be "channels_last" '
                                 '(temporal data).')
        super(Conv1D, self).__init__(
            rank=1,
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            activation=activation,
            use_bias=use_bias,
            kernel_initializer=kernel_initializer,
            bias_initializer=bias_initializer,
            kernel_regularizer=kernel_regularizer,
            bias_regularizer=bias_regularizer,
            activity_regularizer=activity_regularizer,
            kernel_constraint=kernel_constraint,
            bias_constraint=bias_constraint,
            **kwargs)

    def get_config(self):
        config = super(Conv1D, self).get_config()
        config.pop('rank')
        return config


class Conv2D(_Conv):
    """2D convolution layer (e.g. spatial convolution over images).

    This layer creates a convolution kernel that is convolved
    with the layer input to produce a tensor of
    outputs. If `use_bias` is True,
    a bias vector is created and added to the outputs. Finally, if
    `activation` is not `None`, it is applied to the outputs as well.

    When using this layer as the first layer in a model,
    provide the keyword argument `input_shape`
    (tuple of integers, does not include the batch axis),
    e.g. `input_shape=(128, 128, 3)` for 128x128 RGB pictures
    in `data_format="channels_last"`.

    # Arguments
        filters: Integer, the dimensionality of the output space
            (i.e. the number of output filters in the convolution).
        kernel_size: An integer or tuple/list of 2 integers, specifying the
            height and width of the 2D convolution window.
            Can be a single integer to specify the same value for
            all spatial dimensions.
        strides: An integer or tuple/list of 2 integers,
            specifying the strides of the convolution
            along the height and width.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: one of `"valid"` or `"same"` (case-insensitive).
            Note that `"same"` is slightly inconsistent across backends with
            `strides` != 1, as described
            [here](https://github.com/keras-team/keras/pull/9473#issuecomment-372166860)
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, height, width, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, height, width)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
        dilation_rate: an integer or tuple/list of 2 integers, specifying
            the dilation rate to use for dilated convolution.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any stride value != 1.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        kernel_initializer: Initializer for the `kernel` weights matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        kernel_regularizer: Regularizer function applied to
            the `kernel` weights matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its "activation").
            (see [regularizer](../regularizers.md)).
        kernel_constraint: Constraint function applied to the kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).

    # Input shape
        4D tensor with shape:
        `(batch, channels, rows, cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, rows, cols, channels)`
        if `data_format` is `"channels_last"`.

    # Output shape
        4D tensor with shape:
        `(batch, filters, new_rows, new_cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, new_rows, new_cols, filters)`
        if `data_format` is `"channels_last"`.
        `rows` and `cols` values might have changed due to padding.
    """

    @interfaces.legacy_conv2d_support
    def __init__(self, filters,
                 kernel_size,
                 strides=(1, 1),
                 padding='valid',
                 data_format=None,
                 dilation_rate=(1, 1),
                 activation=None,
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 kernel_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(Conv2D, self).__init__(
            rank=2,
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            activation=activation,
            use_bias=use_bias,
            kernel_initializer=kernel_initializer,
            bias_initializer=bias_initializer,
            kernel_regularizer=kernel_regularizer,
            bias_regularizer=bias_regularizer,
            activity_regularizer=activity_regularizer,
            kernel_constraint=kernel_constraint,
            bias_constraint=bias_constraint,
            **kwargs)

    def get_config(self):
        config = super(Conv2D, self).get_config()
        config.pop('rank')
        return config

    def set_lr_multipliers(self, W_learning_rate_multiplier, b_learning_rate_multiplier):
        self.W_learning_rate_multiplier = W_learning_rate_multiplier
        self.b_learning_rate_multiplier = b_learning_rate_multiplier
        self.learning_rate_multipliers = [self.W_learning_rate_multiplier,
                                          self.b_learning_rate_multiplier]


class Conv3D(_Conv):
    """3D convolution layer (e.g. spatial convolution over volumes).

    This layer creates a convolution kernel that is convolved
    with the layer input to produce a tensor of
    outputs. If `use_bias` is True,
    a bias vector is created and added to the outputs. Finally, if
    `activation` is not `None`, it is applied to the outputs as well.

    When using this layer as the first layer in a model,
    provide the keyword argument `input_shape`
    (tuple of integers, does not include the batch axis),
    e.g. `input_shape=(128, 128, 128, 1)` for 128x128x128 volumes
    with a single channel,
    in `data_format="channels_last"`.

    # Arguments
        filters: Integer, the dimensionality of the output space
            (i.e. the number of output filters in the convolution).
        kernel_size: An integer or tuple/list of 3 integers, specifying the
            depth, height and width of the 3D convolution window.
            Can be a single integer to specify the same value for
            all spatial dimensions.
        strides: An integer or tuple/list of 3 integers,
            specifying the strides of the convolution along each spatial dimension.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: one of `"valid"` or `"same"` (case-insensitive).
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, spatial_dim1, spatial_dim2, spatial_dim3, channels)`
            while `"channels_first"` corresponds to inputs with shape
            `(batch, channels, spatial_dim1, spatial_dim2, spatial_dim3)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
        dilation_rate: an integer or tuple/list of 3 integers, specifying
            the dilation rate to use for dilated convolution.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any stride value != 1.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        kernel_initializer: Initializer for the `kernel` weights matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        kernel_regularizer: Regularizer function applied to
            the `kernel` weights matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its "activation").
            (see [regularizer](../regularizers.md)).
        kernel_constraint: Constraint function applied to the kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).

    # Input shape
        5D tensor with shape:
        `(batch, channels, conv_dim1, conv_dim2, conv_dim3)`
        if `data_format` is `"channels_first"`
        or 5D tensor with shape:
        `(batch, conv_dim1, conv_dim2, conv_dim3, channels)`
        if `data_format` is `"channels_last"`.

    # Output shape
        5D tensor with shape:
        `(batch, filters, new_conv_dim1, new_conv_dim2, new_conv_dim3)`
        if `data_format` is `"channels_first"`
        or 5D tensor with shape:
        `(batch, new_conv_dim1, new_conv_dim2, new_conv_dim3, filters)`
        if `data_format` is `"channels_last"`.
        `new_conv_dim1`, `new_conv_dim2` and `new_conv_dim3` values might have
        changed due to padding.
    """

    @interfaces.legacy_conv3d_support
    def __init__(self, filters,
                 kernel_size,
                 strides=(1, 1, 1),
                 padding='valid',
                 data_format=None,
                 dilation_rate=(1, 1, 1),
                 activation=None,
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 kernel_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(Conv3D, self).__init__(
            rank=3,
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            activation=activation,
            use_bias=use_bias,
            kernel_initializer=kernel_initializer,
            bias_initializer=bias_initializer,
            kernel_regularizer=kernel_regularizer,
            bias_regularizer=bias_regularizer,
            activity_regularizer=activity_regularizer,
            kernel_constraint=kernel_constraint,
            bias_constraint=bias_constraint,
            **kwargs)

    def get_config(self):
        config = super(Conv3D, self).get_config()
        config.pop('rank')
        return config


class Conv2DTranspose(Conv2D):
    """Transposed convolution layer (sometimes called Deconvolution).

    The need for transposed convolutions generally arises
    from the desire to use a transformation going in the opposite direction
    of a normal convolution, i.e., from something that has the shape of the
    output of some convolution to something that has the shape of its input
    while maintaining a connectivity pattern that is compatible with
    said convolution.

    When using this layer as the first layer in a model,
    provide the keyword argument `input_shape`
    (tuple of integers, does not include the batch axis),
    e.g. `input_shape=(128, 128, 3)` for 128x128 RGB pictures
    in `data_format="channels_last"`.

    # Arguments
        filters: Integer, the dimensionality of the output space
            (i.e. the number of output filters in the convolution).
        kernel_size: An integer or tuple/list of 2 integers, specifying the
            height and width of the 2D convolution window.
            Can be a single integer to specify the same value for
            all spatial dimensions.
        strides: An integer or tuple/list of 2 integers,
            specifying the strides of the convolution
            along the height and width.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: one of `"valid"` or `"same"` (case-insensitive).
        output_padding: An integer or tuple/list of 2 integers,
            specifying the amount of padding along the height and width
            of the output tensor.
            Can be a single integer to specify the same value for all
            spatial dimensions.
            The amount of output padding along a given dimension must be
            lower than the stride along that same dimension.
            If set to `None` (default), the output shape is inferred.
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, height, width, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, height, width)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
        dilation_rate: an integer or tuple/list of 2 integers, specifying
            the dilation rate to use for dilated convolution.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any stride value != 1.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        kernel_initializer: Initializer for the `kernel` weights matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        kernel_regularizer: Regularizer function applied to
            the `kernel` weights matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its "activation").
            (see [regularizer](../regularizers.md)).
        kernel_constraint: Constraint function applied to the kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).

    # Input shape
        4D tensor with shape:
        `(batch, channels, rows, cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, rows, cols, channels)`
        if `data_format` is `"channels_last"`.

    # Output shape
        4D tensor with shape:
        `(batch, filters, new_rows, new_cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, new_rows, new_cols, filters)`
        if `data_format` is `"channels_last"`.
        `rows` and `cols` values might have changed due to padding.
        If `output_padding` is specified:

        ```
        new_rows = ((rows - 1) * strides[0] + kernel_size[0]
                    - 2 * padding[0] + output_padding[0])
        new_cols = ((cols - 1) * strides[1] + kernel_size[1]
                    - 2 * padding[1] + output_padding[1])
        ```

    # References
        - [A guide to convolution arithmetic for deep learning](
           https://arxiv.org/abs/1603.07285v1)
        - [Deconvolutional Networks](
           https://www.matthewzeiler.com/mattzeiler/deconvolutionalnetworks.pdf)
    """

    @interfaces.legacy_deconv2d_support
    def __init__(self, filters,
                 kernel_size,
                 strides=(1, 1),
                 padding='valid',
                 output_padding=None,
                 data_format=None,
                 dilation_rate=(1, 1),
                 activation=None,
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 kernel_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(Conv2DTranspose, self).__init__(
            filters,
            kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            activation=activation,
            use_bias=use_bias,
            kernel_initializer=kernel_initializer,
            bias_initializer=bias_initializer,
            kernel_regularizer=kernel_regularizer,
            bias_regularizer=bias_regularizer,
            activity_regularizer=activity_regularizer,
            kernel_constraint=kernel_constraint,
            bias_constraint=bias_constraint,
            **kwargs)

        self.output_padding = output_padding
        if self.output_padding is not None:
            self.output_padding = conv_utils.normalize_tuple(
                self.output_padding, 2, 'output_padding')
            for stride, out_pad in zip(self.strides, self.output_padding):
                if out_pad >= stride:
                    raise ValueError('Stride ' + str(self.strides) + ' must be '
                                     'greater than output padding ' +
                                     str(self.output_padding))

    def build(self, input_shape):
        if len(input_shape) != 4:
            raise ValueError('Inputs should have rank ' +
                             str(4) +
                             '; Received input shape:', str(input_shape))
        if self.data_format == 'channels_first':
            channel_axis = 1
        else:
            channel_axis = -1
        if input_shape[channel_axis] is None:
            raise ValueError('The channel dimension of the inputs '
                             'should be defined. Found `None`.')
        input_dim = input_shape[channel_axis]
        kernel_shape = self.kernel_size + (self.filters, input_dim)

        self.kernel = self.add_weight(shape=kernel_shape,
                                      initializer=self.kernel_initializer,
                                      name='kernel',
                                      regularizer=self.kernel_regularizer,
                                      constraint=self.kernel_constraint)
        if self.use_bias:
            self.bias = self.add_weight(shape=(self.filters,),
                                        initializer=self.bias_initializer,
                                        name='bias',
                                        regularizer=self.bias_regularizer,
                                        constraint=self.bias_constraint)
        else:
            self.bias = None
        # Set input spec.
        self.input_spec = InputSpec(ndim=4, axes={channel_axis: input_dim})
        self.built = True

    def call(self, inputs):
        input_shape = K.shape(inputs)
        batch_size = input_shape[0]
        if self.data_format == 'channels_first':
            h_axis, w_axis = 2, 3
        else:
            h_axis, w_axis = 1, 2

        height, width = input_shape[h_axis], input_shape[w_axis]
        kernel_h, kernel_w = self.kernel_size
        stride_h, stride_w = self.strides
        if self.output_padding is None:
            out_pad_h = out_pad_w = None
        else:
            out_pad_h, out_pad_w = self.output_padding

        # Infer the dynamic output shape:
        out_height = conv_utils.deconv_length(height,
                                              stride_h, kernel_h,
                                              self.padding,
                                              out_pad_h,
                                              self.dilation_rate[0])
        out_width = conv_utils.deconv_length(width,
                                             stride_w, kernel_w,
                                             self.padding,
                                             out_pad_w,
                                             self.dilation_rate[1])
        if self.data_format == 'channels_first':
            output_shape = (batch_size, self.filters, out_height, out_width)
        else:
            output_shape = (batch_size, out_height, out_width, self.filters)

        outputs = K.conv2d_transpose(
            inputs,
            self.kernel,
            output_shape,
            self.strides,
            padding=self.padding,
            data_format=self.data_format,
            dilation_rate=self.dilation_rate)

        if self.use_bias:
            outputs = K.bias_add(
                outputs,
                self.bias,
                data_format=self.data_format)

        if self.activation is not None:
            return self.activation(outputs)
        return outputs

    def compute_output_shape(self, input_shape):
        output_shape = list(input_shape)
        if self.data_format == 'channels_first':
            c_axis, h_axis, w_axis = 1, 2, 3
        else:
            c_axis, h_axis, w_axis = 3, 1, 2

        kernel_h, kernel_w = self.kernel_size
        stride_h, stride_w = self.strides
        if self.output_padding is None:
            out_pad_h = out_pad_w = None
        else:
            out_pad_h, out_pad_w = self.output_padding

        output_shape[c_axis] = self.filters
        output_shape[h_axis] = conv_utils.deconv_length(output_shape[h_axis],
                                                        stride_h,
                                                        kernel_h,
                                                        self.padding,
                                                        out_pad_h,
                                                        self.dilation_rate[0])
        output_shape[w_axis] = conv_utils.deconv_length(output_shape[w_axis],
                                                        stride_w,
                                                        kernel_w,
                                                        self.padding,
                                                        out_pad_w,
                                                        self.dilation_rate[1])
        return tuple(output_shape)

    def get_config(self):
        config = super(Conv2DTranspose, self).get_config()
        config['output_padding'] = self.output_padding
        return config

    def set_lr_multipliers(self, W_learning_rate_multiplier, b_learning_rate_multiplier):
        self.W_learning_rate_multiplier = W_learning_rate_multiplier
        self.b_learning_rate_multiplier = b_learning_rate_multiplier
        self.learning_rate_multipliers = [self.W_learning_rate_multiplier,
                                          self.b_learning_rate_multiplier]


class Conv3DTranspose(Conv3D):
    """Transposed convolution layer (sometimes called Deconvolution).

    The need for transposed convolutions generally arises
    from the desire to use a transformation going in the opposite direction
    of a normal convolution, i.e., from something that has the shape of the
    output of some convolution to something that has the shape of its input
    while maintaining a connectivity pattern that is compatible with
    said convolution.

    When using this layer as the first layer in a model,
    provide the keyword argument `input_shape`
    (tuple of integers, does not include the batch axis),
    e.g. `input_shape=(128, 128, 128, 3)` for a 128x128x128 volume with 3 channels
    if `data_format="channels_last"`.

    # Arguments
        filters: Integer, the dimensionality of the output space
            (i.e. the number of output filters in the convolution).
        kernel_size: An integer or tuple/list of 3 integers, specifying the
            depth, height and width of the 3D convolution window.
            Can be a single integer to specify the same value for
            all spatial dimensions.
        strides: An integer or tuple/list of 3 integers,
            specifying the strides of the convolution
            along the depth, height and width.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: one of `"valid"` or `"same"` (case-insensitive).
        output_padding: An integer or tuple/list of 3 integers,
            specifying the amount of padding along the depth, height, and
            width.
            Can be a single integer to specify the same value for all
            spatial dimensions.
            The amount of output padding along a given dimension must be
            lower than the stride along that same dimension.
            If set to `None` (default), the output shape is inferred.
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, depth, height, width, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, depth, height, width)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
        dilation_rate: an integer or tuple/list of 3 integers, specifying
            the dilation rate to use for dilated convolution.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any stride value != 1.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        kernel_initializer: Initializer for the `kernel` weights matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        kernel_regularizer: Regularizer function applied to
            the `kernel` weights matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its "activation").
            (see [regularizer](../regularizers.md)).
        kernel_constraint: Constraint function applied to the kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).

    # Input shape
        5D tensor with shape:
        `(batch, channels, depth, rows, cols)`
        if `data_format` is `"channels_first"`
        or 5D tensor with shape:
        `(batch, depth, rows, cols, channels)`
        if `data_format` is `"channels_last"`.

    # Output shape
        5D tensor with shape:
        `(batch, filters, new_depth, new_rows, new_cols)`
        if `data_format` is `"channels_first"`
        or 5D tensor with shape:
        `(batch, new_depth, new_rows, new_cols, filters)`
        if `data_format` is `"channels_last"`.
        `depth` and `rows` and `cols` values might have changed due to padding.
        If `output_padding` is specified::

        ```
        new_depth = ((depth - 1) * strides[0] + kernel_size[0]
                     - 2 * padding[0] + output_padding[0])
        new_rows = ((rows - 1) * strides[1] + kernel_size[1]
                    - 2 * padding[1] + output_padding[1])
        new_cols = ((cols - 1) * strides[2] + kernel_size[2]
                    - 2 * padding[2] + output_padding[2])
        ```

    # References
        - [A guide to convolution arithmetic for deep learning](
           https://arxiv.org/abs/1603.07285v1)
        - [Deconvolutional Networks](
           https://www.matthewzeiler.com/mattzeiler/deconvolutionalnetworks.pdf)
    """

    def __init__(self, filters,
                 kernel_size,
                 strides=(1, 1, 1),
                 padding='valid',
                 output_padding=None,
                 data_format=None,
                 activation=None,
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 kernel_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(Conv3DTranspose, self).__init__(
            filters,
            kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            activation=activation,
            use_bias=use_bias,
            kernel_initializer=kernel_initializer,
            bias_initializer=bias_initializer,
            kernel_regularizer=kernel_regularizer,
            bias_regularizer=bias_regularizer,
            activity_regularizer=activity_regularizer,
            kernel_constraint=kernel_constraint,
            bias_constraint=bias_constraint,
            **kwargs)

        self.output_padding = output_padding
        if self.output_padding is not None:
            self.output_padding = conv_utils.normalize_tuple(
                self.output_padding, 3, 'output_padding')
            for stride, out_pad in zip(self.strides, self.output_padding):
                if out_pad >= stride:
                    raise ValueError('Stride ' + str(self.strides) + ' must be '
                                     'greater than output padding ' +
                                     str(self.output_padding))

    def build(self, input_shape):
        if len(input_shape) != 5:
            raise ValueError('Inputs should have rank ' +
                             str(5) +
                             '; Received input shape:', str(input_shape))
        if self.data_format == 'channels_first':
            channel_axis = 1
        else:
            channel_axis = -1
        if input_shape[channel_axis] is None:
            raise ValueError('The channel dimension of the inputs '
                             'should be defined. Found `None`.')
        input_dim = input_shape[channel_axis]
        kernel_shape = self.kernel_size + (self.filters, input_dim)

        self.kernel = self.add_weight(shape=kernel_shape,
                                      initializer=self.kernel_initializer,
                                      name='kernel',
                                      regularizer=self.kernel_regularizer,
                                      constraint=self.kernel_constraint)
        if self.use_bias:
            self.bias = self.add_weight(shape=(self.filters,),
                                        initializer=self.bias_initializer,
                                        name='bias',
                                        regularizer=self.bias_regularizer,
                                        constraint=self.bias_constraint)
        else:
            self.bias = None
        # Set input spec.
        self.input_spec = InputSpec(ndim=5, axes={channel_axis: input_dim})
        self.built = True

    def call(self, inputs):
        input_shape = K.shape(inputs)
        batch_size = input_shape[0]
        if self.data_format == 'channels_first':
            d_axis, h_axis, w_axis = 2, 3, 4
        else:
            d_axis, h_axis, w_axis = 1, 2, 3

        depth = input_shape[d_axis]
        height = input_shape[h_axis]
        width = input_shape[w_axis]

        kernel_d, kernel_h, kernel_w = self.kernel_size
        stride_d, stride_h, stride_w = self.strides
        if self.output_padding is None:
            out_pad_d = out_pad_h = out_pad_w = None
        else:
            out_pad_d, out_pad_h, out_pad_w = self.output_padding

        # Infer the dynamic output shape:
        out_depth = conv_utils.deconv_length(depth,
                                             stride_d, kernel_d,
                                             self.padding,
                                             out_pad_d)
        out_height = conv_utils.deconv_length(height,
                                              stride_h, kernel_h,
                                              self.padding,
                                              out_pad_h)
        out_width = conv_utils.deconv_length(width,
                                             stride_w, kernel_w,
                                             self.padding,
                                             out_pad_w)

        if self.data_format == 'channels_first':
            output_shape = (batch_size, self.filters,
                            out_depth, out_height, out_width)
        else:
            output_shape = (batch_size, out_depth,
                            out_height, out_width, self.filters)

        outputs = K.conv3d_transpose(inputs,
                                     self.kernel,
                                     output_shape,
                                     self.strides,
                                     padding=self.padding,
                                     data_format=self.data_format)

        if self.use_bias:
            outputs = K.bias_add(
                outputs,
                self.bias,
                data_format=self.data_format)

        if self.activation is not None:
            return self.activation(outputs)
        return outputs

    def compute_output_shape(self, input_shape):
        output_shape = list(input_shape)
        if self.data_format == 'channels_first':
            c_axis, d_axis, h_axis, w_axis = 1, 2, 3, 4
        else:
            c_axis, d_axis, h_axis, w_axis = 4, 1, 2, 3

        kernel_d, kernel_h, kernel_w = self.kernel_size
        stride_d, stride_h, stride_w = self.strides
        if self.output_padding is None:
            out_pad_d = out_pad_h = out_pad_w = None
        else:
            out_pad_d, out_pad_h, out_pad_w = self.output_padding

        output_shape[c_axis] = self.filters
        output_shape[d_axis] = conv_utils.deconv_length(output_shape[d_axis],
                                                        stride_d,
                                                        kernel_d,
                                                        self.padding,
                                                        out_pad_d)
        output_shape[h_axis] = conv_utils.deconv_length(output_shape[h_axis],
                                                        stride_h,
                                                        kernel_h,
                                                        self.padding,
                                                        out_pad_h)
        output_shape[w_axis] = conv_utils.deconv_length(output_shape[w_axis],
                                                        stride_w,
                                                        kernel_w,
                                                        self.padding,
                                                        out_pad_w)

        return tuple(output_shape)

    def get_config(self):
        config = super(Conv3DTranspose, self).get_config()
        config.pop('dilation_rate')
        config['output_padding'] = self.output_padding
        return config


class _SeparableConv(_Conv):
    """Abstract nD depthwise separable convolution layer (private).

    Separable convolutions consist in first performing
    a depthwise spatial convolution
    (which acts on each input channel separately)
    followed by a pointwise convolution which mixes together the resulting
    output channels. The `depth_multiplier` argument controls how many
    output channels are generated per input channel in the depthwise step.

    Intuitively, separable convolutions can be understood as
    a way to factorize a convolution kernel into two smaller kernels,
    or as an extreme version of an Inception block.

    # Arguments
        rank: An integer, the rank of the convolution,
            e.g. "2" for 2D convolution.
        filters: Integer, the dimensionality of the output space
            (i.e. the number of output filters in the convolution).
        kernel_size: An integer or tuple/list of 2 integers, specifying the
            height and width of the 2D convolution window.
            Can be a single integer to specify the same value for
            all spatial dimensions.
        strides: An integer or tuple/list of 2 integers,
            specifying the strides of the convolution
            along the height and width.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: one of `"valid"` or `"same"` (case-insensitive).
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, height, width, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, height, width)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
        dilation_rate: an integer or tuple/list of n integers, specifying
            the dilation rate to use for dilated convolution.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any stride value != 1.
        depth_multiplier: The number of depthwise convolution output channels
            for each input channel.
            The total number of depthwise convolution output
            channels will be equal to `filters_in * depth_multiplier`.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        depthwise_initializer: Initializer for the depthwise kernel matrix
            (see [initializers](../initializers.md)).
        pointwise_initializer: Initializer for the pointwise kernel matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        depthwise_regularizer: Regularizer function applied to
            the depthwise kernel matrix
            (see [regularizer](../regularizers.md)).
        pointwise_regularizer: Regularizer function applied to
            the pointwise kernel matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its "activation").
            (see [regularizer](../regularizers.md)).
        depthwise_constraint: Constraint function applied to
            the depthwise kernel matrix
            (see [constraints](../constraints.md)).
        pointwise_constraint: Constraint function applied to
            the pointwise kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).

    # Input shape
        4D tensor with shape:
        `(batch, channels, rows, cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, rows, cols, channels)`
        if `data_format` is `"channels_last"`.

    # Output shape
        4D tensor with shape:
        `(batch, filters, new_rows, new_cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, new_rows, new_cols, filters)`
        if `data_format` is `"channels_last"`.
        `rows` and `cols` values might have changed due to padding.
    """

    def __init__(self, rank,
                 filters,
                 kernel_size,
                 strides=1,
                 padding='valid',
                 data_format=None,
                 dilation_rate=1,
                 depth_multiplier=1,
                 activation=None,
                 use_bias=True,
                 depthwise_initializer='glorot_uniform',
                 pointwise_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 depthwise_regularizer=None,
                 pointwise_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 depthwise_constraint=None,
                 pointwise_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(_SeparableConv, self).__init__(
            rank=rank,
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            activation=activation,
            use_bias=use_bias,
            bias_initializer=bias_initializer,
            bias_regularizer=bias_regularizer,
            activity_regularizer=activity_regularizer,
            bias_constraint=bias_constraint,
            **kwargs)
        self.depth_multiplier = depth_multiplier
        self.depthwise_initializer = initializers.get(depthwise_initializer)
        self.pointwise_initializer = initializers.get(pointwise_initializer)
        self.depthwise_regularizer = regularizers.get(depthwise_regularizer)
        self.pointwise_regularizer = regularizers.get(pointwise_regularizer)
        self.depthwise_constraint = constraints.get(depthwise_constraint)
        self.pointwise_constraint = constraints.get(pointwise_constraint)

    def build(self, input_shape):
        if len(input_shape) < self.rank + 2:
            raise ValueError('Inputs to `SeparableConv' + str(self.rank) + 'D` '
                             'should have rank ' + str(self.rank + 2) + '. '
                             'Received input shape:', str(input_shape))
        channel_axis = 1 if self.data_format == 'channels_first' else -1
        if input_shape[channel_axis] is None:
            raise ValueError('The channel dimension of the inputs '
                             'should be defined. Found `None`.')
        input_dim = int(input_shape[channel_axis])
        depthwise_kernel_shape = (input_dim, self.depth_multiplier)
        depthwise_kernel_shape = self.kernel_size + depthwise_kernel_shape
        pointwise_kernel_shape = (self.depth_multiplier * input_dim, self.filters)
        pointwise_kernel_shape = (1,) * self.rank + pointwise_kernel_shape

        self.depthwise_kernel = self.add_weight(
            shape=depthwise_kernel_shape,
            initializer=self.depthwise_initializer,
            name='depthwise_kernel',
            regularizer=self.depthwise_regularizer,
            constraint=self.depthwise_constraint)
        self.pointwise_kernel = self.add_weight(
            shape=pointwise_kernel_shape,
            initializer=self.pointwise_initializer,
            name='pointwise_kernel',
            regularizer=self.pointwise_regularizer,
            constraint=self.pointwise_constraint)

        if self.use_bias:
            self.bias = self.add_weight(shape=(self.filters,),
                                        initializer=self.bias_initializer,
                                        name='bias',
                                        regularizer=self.bias_regularizer,
                                        constraint=self.bias_constraint)
        else:
            self.bias = None
        # Set input spec.
        self.input_spec = InputSpec(ndim=self.rank + 2,
                                    axes={channel_axis: input_dim})
        self.built = True

    def call(self, inputs):
        if self.rank == 1:
            outputs = K.separable_conv1d(
                inputs,
                self.depthwise_kernel,
                self.pointwise_kernel,
                data_format=self.data_format,
                strides=self.strides,
                padding=self.padding,
                dilation_rate=self.dilation_rate)
        if self.rank == 2:
            outputs = K.separable_conv2d(
                inputs,
                self.depthwise_kernel,
                self.pointwise_kernel,
                data_format=self.data_format,
                strides=self.strides,
                padding=self.padding,
                dilation_rate=self.dilation_rate)

        if self.use_bias:
            outputs = K.bias_add(
                outputs,
                self.bias,
                data_format=self.data_format)

        if self.activation is not None:
            return self.activation(outputs)
        return outputs

    def get_config(self):
        config = super(_SeparableConv, self).get_config()
        config.pop('rank')
        config.pop('kernel_initializer')
        config.pop('kernel_regularizer')
        config.pop('kernel_constraint')
        config['depth_multiplier'] = self.depth_multiplier
        config['depthwise_initializer'] = (
            initializers.serialize(self.depthwise_initializer))
        config['pointwise_initializer'] = (
            initializers.serialize(self.pointwise_initializer))
        config['depthwise_regularizer'] = (
            regularizers.serialize(self.depthwise_regularizer))
        config['pointwise_regularizer'] = (
            regularizers.serialize(self.pointwise_regularizer))
        config['depthwise_constraint'] = (
            constraints.serialize(self.depthwise_constraint))
        config['pointwise_constraint'] = (
            constraints.serialize(self.pointwise_constraint))
        return config


class SeparableConv1D(_SeparableConv):
    """Depthwise separable 1D convolution.

    Separable convolutions consist in first performing
    a depthwise spatial convolution
    (which acts on each input channel separately)
    followed by a pointwise convolution which mixes together the resulting
    output channels. The `depth_multiplier` argument controls how many
    output channels are generated per input channel in the depthwise step.

    Intuitively, separable convolutions can be understood as
    a way to factorize a convolution kernel into two smaller kernels,
    or as an extreme version of an Inception block.

    # Arguments
        filters: Integer, the dimensionality of the output space
            (i.e. the number of output filters in the convolution).
        kernel_size: An integer or tuple/list of single integer,
            specifying the length of the 1D convolution window.
        strides: An integer or tuple/list of single integer,
            specifying the stride length of the convolution.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: one of `"valid"` or `"same"` (case-insensitive).
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, steps, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, steps)`.
        dilation_rate: An integer or tuple/list of a single integer, specifying
            the dilation rate to use for dilated convolution.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any `strides` value != 1.
        depth_multiplier: The number of depthwise convolution output channels
            for each input channel.
            The total number of depthwise convolution output
            channels will be equal to `filters_in * depth_multiplier`.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        depthwise_initializer: Initializer for the depthwise kernel matrix
            (see [initializers](../initializers.md)).
        pointwise_initializer: Initializer for the pointwise kernel matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        depthwise_regularizer: Regularizer function applied to
            the depthwise kernel matrix
            (see [regularizer](../regularizers.md)).
        pointwise_regularizer: Regularizer function applied to
            the pointwise kernel matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its "activation").
            (see [regularizer](../regularizers.md)).
        depthwise_constraint: Constraint function applied to
            the depthwise kernel matrix
            (see [constraints](../constraints.md)).
        pointwise_constraint: Constraint function applied to
            the pointwise kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).

    # Input shape
        3D tensor with shape:
        `(batch, channels, steps)`
        if `data_format` is `"channels_first"`
        or 3D tensor with shape:
        `(batch, steps, channels)`
        if `data_format` is `"channels_last"`.

    # Output shape
        3D tensor with shape:
        `(batch, filters, new_steps)`
        if `data_format` is `"channels_first"`
        or 3D tensor with shape:
        `(batch, new_steps, filters)`
        if `data_format` is `"channels_last"`.
        `new_steps` values might have changed due to padding or strides.
    """

    def __init__(self, filters,
                 kernel_size,
                 strides=1,
                 padding='valid',
                 data_format='channels_last',
                 dilation_rate=1,
                 depth_multiplier=1,
                 activation=None,
                 use_bias=True,
                 depthwise_initializer='glorot_uniform',
                 pointwise_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 depthwise_regularizer=None,
                 pointwise_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 depthwise_constraint=None,
                 pointwise_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(SeparableConv1D, self).__init__(
            rank=1,
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            depth_multiplier=depth_multiplier,
            activation=activation,
            use_bias=use_bias,
            depthwise_initializer=depthwise_initializer,
            pointwise_initializer=pointwise_initializer,
            bias_initializer=bias_initializer,
            depthwise_regularizer=depthwise_regularizer,
            pointwise_regularizer=pointwise_regularizer,
            bias_regularizer=bias_regularizer,
            activity_regularizer=activity_regularizer,
            depthwise_constraint=depthwise_constraint,
            pointwise_constraint=pointwise_constraint,
            bias_constraint=bias_constraint,
            **kwargs)


class SeparableConv2D(_SeparableConv):
    """Depthwise separable 2D convolution.

    Separable convolutions consist in first performing
    a depthwise spatial convolution
    (which acts on each input channel separately)
    followed by a pointwise convolution which mixes together the resulting
    output channels. The `depth_multiplier` argument controls how many
    output channels are generated per input channel in the depthwise step.

    Intuitively, separable convolutions can be understood as
    a way to factorize a convolution kernel into two smaller kernels,
    or as an extreme version of an Inception block.

    # Arguments
        filters: Integer, the dimensionality of the output space
            (i.e. the number of output filters in the convolution).
        kernel_size: An integer or tuple/list of 2 integers, specifying the
            height and width of the 2D convolution window.
            Can be a single integer to specify the same value for
            all spatial dimensions.
        strides: An integer or tuple/list of 2 integers,
            specifying the strides of the convolution
            along the height and width.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: one of `"valid"` or `"same"` (case-insensitive).
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, height, width, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, height, width)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
        dilation_rate: An integer or tuple/list of 2 integers, specifying
            the dilation rate to use for dilated convolution.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any `strides` value != 1.
        depth_multiplier: The number of depthwise convolution output channels
            for each input channel.
            The total number of depthwise convolution output
            channels will be equal to `filters_in * depth_multiplier`.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. "linear" activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        depthwise_initializer: Initializer for the depthwise kernel matrix
            (see [initializers](../initializers.md)).
        pointwise_initializer: Initializer for the pointwise kernel matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        depthwise_regularizer: Regularizer function applied to
            the depthwise kernel matrix
            (see [regularizer](../regularizers.md)).
        pointwise_regularizer: Regularizer function applied to
            the pointwise kernel matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its "activation").
            (see [regularizer](../regularizers.md)).
        depthwise_constraint: Constraint function applied to
            the depthwise kernel matrix
            (see [constraints](../constraints.md)).
        pointwise_constraint: Constraint function applied to
            the pointwise kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).

    # Input shape
        4D tensor with shape:
        `(batch, channels, rows, cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, rows, cols, channels)`
        if `data_format` is `"channels_last"`.

    # Output shape
        4D tensor with shape:
        `(batch, filters, new_rows, new_cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, new_rows, new_cols, filters)`
        if `data_format` is `"channels_last"`.
        `rows` and `cols` values might have changed due to padding.
    """

    @interfaces.legacy_separable_conv2d_support
    def __init__(self, filters,
                 kernel_size,
                 strides=(1, 1),
                 padding='valid',
                 data_format=None,
                 dilation_rate=(1, 1),
                 depth_multiplier=1,
                 activation=None,
                 use_bias=True,
                 depthwise_initializer='glorot_uniform',
                 pointwise_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 depthwise_regularizer=None,
                 pointwise_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 depthwise_constraint=None,
                 pointwise_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(SeparableConv2D, self).__init__(
            rank=2,
            filters=filters,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            depth_multiplier=depth_multiplier,
            activation=activation,
            use_bias=use_bias,
            depthwise_initializer=depthwise_initializer,
            pointwise_initializer=pointwise_initializer,
            bias_initializer=bias_initializer,
            depthwise_regularizer=depthwise_regularizer,
            pointwise_regularizer=pointwise_regularizer,
            bias_regularizer=bias_regularizer,
            activity_regularizer=activity_regularizer,
            depthwise_constraint=depthwise_constraint,
            pointwise_constraint=pointwise_constraint,
            bias_constraint=bias_constraint,
            **kwargs)


class DepthwiseConv2D(Conv2D):
    """Depthwise separable 2D convolution.

    Depthwise Separable convolutions consists in performing
    just the first step in a depthwise spatial convolution
    (which acts on each input channel separately).
    The `depth_multiplier` argument controls how many
    output channels are generated per input channel in the depthwise step.

    # Arguments
        kernel_size: An integer or tuple/list of 2 integers, specifying the
            height and width of the 2D convolution window.
            Can be a single integer to specify the same value for
            all spatial dimensions.
        strides: An integer or tuple/list of 2 integers,
            specifying the strides of the convolution
            along the height and width.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Specifying any stride value != 1 is incompatible with specifying
            any `dilation_rate` value != 1.
        padding: one of `"valid"` or `"same"` (case-insensitive).
        depth_multiplier: The number of depthwise convolution output channels
            for each input channel.
            The total number of depthwise convolution output
            channels will be equal to `filters_in * depth_multiplier`.
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, height, width, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, height, width)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be 'channels_last'.
        dilation_rate: an integer or tuple/list of 2 integers, specifying
            the dilation rate to use for dilated convolution.
            Can be a single integer to specify the same value for
            all spatial dimensions.
            Currently, specifying any `dilation_rate` value != 1 is
            incompatible with specifying any stride value != 1.
        activation: Activation function to use
            (see [activations](../activations.md)).
            If you don't specify anything, no activation is applied
            (ie. 'linear' activation: `a(x) = x`).
        use_bias: Boolean, whether the layer uses a bias vector.
        depthwise_initializer: Initializer for the depthwise kernel matrix
            (see [initializers](../initializers.md)).
        bias_initializer: Initializer for the bias vector
            (see [initializers](../initializers.md)).
        depthwise_regularizer: Regularizer function applied to
            the depthwise kernel matrix
            (see [regularizer](../regularizers.md)).
        bias_regularizer: Regularizer function applied to the bias vector
            (see [regularizer](../regularizers.md)).
        activity_regularizer: Regularizer function applied to
            the output of the layer (its 'activation').
            (see [regularizer](../regularizers.md)).
        depthwise_constraint: Constraint function applied to
            the depthwise kernel matrix
            (see [constraints](../constraints.md)).
        bias_constraint: Constraint function applied to the bias vector
            (see [constraints](../constraints.md)).

    # Input shape
        4D tensor with shape:
        `(batch, channels, rows, cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, rows, cols, channels)`
        if `data_format` is `"channels_last"`.

    # Output shape
        4D tensor with shape:
        `(batch, filters, new_rows, new_cols)`
        if `data_format` is `"channels_first"`
        or 4D tensor with shape:
        `(batch, new_rows, new_cols, filters)`
        if `data_format` is `"channels_last"`.
        `rows` and `cols` values might have changed due to padding.
    """

    def __init__(self,
                 kernel_size,
                 strides=(1, 1),
                 padding='valid',
                 depth_multiplier=1,
                 data_format=None,
                 dilation_rate=(1, 1),
                 activation=None,
                 use_bias=True,
                 depthwise_initializer='glorot_uniform',
                 bias_initializer='zeros',
                 depthwise_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 depthwise_constraint=None,
                 bias_constraint=None,
                 **kwargs):
        super(DepthwiseConv2D, self).__init__(
            filters=None,
            kernel_size=kernel_size,
            strides=strides,
            padding=padding,
            data_format=data_format,
            dilation_rate=dilation_rate,
            activation=activation,
            use_bias=use_bias,
            bias_regularizer=bias_regularizer,
            activity_regularizer=activity_regularizer,
            bias_constraint=bias_constraint,
            **kwargs)
        self.depth_multiplier = depth_multiplier
        self.depthwise_initializer = initializers.get(depthwise_initializer)
        self.depthwise_regularizer = regularizers.get(depthwise_regularizer)
        self.depthwise_constraint = constraints.get(depthwise_constraint)
        self.bias_initializer = initializers.get(bias_initializer)

    def build(self, input_shape):
        if len(input_shape) < 4:
            raise ValueError('Inputs to `DepthwiseConv2D` should have rank 4. '
                             'Received input shape:', str(input_shape))
        if self.data_format == 'channels_first':
            channel_axis = 1
        else:
            channel_axis = 3
        if input_shape[channel_axis] is None:
            raise ValueError('The channel dimension of the inputs to '
                             '`DepthwiseConv2D` '
                             'should be defined. Found `None`.')
        input_dim = int(input_shape[channel_axis])
        depthwise_kernel_shape = (self.kernel_size[0],
                                  self.kernel_size[1],
                                  input_dim,
                                  self.depth_multiplier)

        self.depthwise_kernel = self.add_weight(
            shape=depthwise_kernel_shape,
            initializer=self.depthwise_initializer,
            name='depthwise_kernel',
            regularizer=self.depthwise_regularizer,
            constraint=self.depthwise_constraint)

        if self.use_bias:
            self.bias = self.add_weight(shape=(input_dim * self.depth_multiplier,),
                                        initializer=self.bias_initializer,
                                        name='bias',
                                        regularizer=self.bias_regularizer,
                                        constraint=self.bias_constraint)
        else:
            self.bias = None
        # Set input spec.
        self.input_spec = InputSpec(ndim=4, axes={channel_axis: input_dim})
        self.built = True

    def call(self, inputs, training=None):
        outputs = K.depthwise_conv2d(
            inputs,
            self.depthwise_kernel,
            strides=self.strides,
            padding=self.padding,
            dilation_rate=self.dilation_rate,
            data_format=self.data_format)

        if self.use_bias:
            outputs = K.bias_add(
                outputs,
                self.bias,
                data_format=self.data_format)

        if self.activation is not None:
            return self.activation(outputs)

        return outputs

    def compute_output_shape(self, input_shape):
        if self.data_format == 'channels_last':
            space = input_shape[1:-1]
            out_filters = input_shape[3] * self.depth_multiplier
        elif self.data_format == 'channels_first':
            space = input_shape[2:]
            out_filters = input_shape[1] * self.depth_multiplier
        new_space = []
        for i in range(len(space)):
            new_dim = conv_utils.conv_output_length(
                space[i],
                self.kernel_size[i],
                padding=self.padding,
                stride=self.strides[i],
                dilation=self.dilation_rate[i])
            new_space.append(new_dim)
        if self.data_format == 'channels_last':
            return (input_shape[0], new_space[0], new_space[1], out_filters)
        elif self.data_format == 'channels_first':
            return (input_shape[0], out_filters, new_space[0], new_space[1])

    def get_config(self):
        config = super(DepthwiseConv2D, self).get_config()
        config.pop('filters')
        config.pop('kernel_initializer')
        config.pop('kernel_regularizer')
        config.pop('kernel_constraint')
        config['depth_multiplier'] = self.depth_multiplier
        config['depthwise_initializer'] = (
            initializers.serialize(self.depthwise_initializer))
        config['depthwise_regularizer'] = (
            regularizers.serialize(self.depthwise_regularizer))
        config['depthwise_constraint'] = (
            constraints.serialize(self.depthwise_constraint))
        return config


class _UpSampling(Layer):
    """Abstract nD UpSampling layer (private, used as implementation base).

    # Arguments
        size: Tuple of ints.
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, ..., channels)` while `"channels_first"` corresponds to
            inputs with shape `(batch, channels, ...)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
    """
    def __init__(self, size, data_format=None, **kwargs):
        # self.rank is 1 for UpSampling1D, 2 for UpSampling2D.
        self.rank = len(size)
        self.size = size
        self.data_format = K.normalize_data_format(data_format)
        self.input_spec = InputSpec(ndim=self.rank + 2)
        super(_UpSampling, self).__init__(**kwargs)

    def call(self, inputs):
        raise NotImplementedError

    def compute_output_shape(self, input_shape):
        size_all_dims = (1,) + self.size + (1,)
        spatial_axes = list(range(1, 1 + self.rank))
        size_all_dims = transpose_shape(size_all_dims,
                                        self.data_format,
                                        spatial_axes)
        output_shape = list(input_shape)
        for dim in range(len(output_shape)):
            if output_shape[dim] is not None:
                output_shape[dim] *= size_all_dims[dim]
        return tuple(output_shape)

    def get_config(self):
        config = {'size': self.size,
                  'data_format': self.data_format}
        base_config = super(_UpSampling, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))


class UpSampling1D(_UpSampling):
    """Upsampling layer for 1D inputs.

    Repeats each temporal step `size` times along the time axis.

    # Arguments
        size: integer. Upsampling factor.

    # Input shape
        3D tensor with shape: `(batch, steps, features)`.

    # Output shape
        3D tensor with shape: `(batch, upsampled_steps, features)`.
    """

    @interfaces.legacy_upsampling1d_support
    def __init__(self, size=2, **kwargs):
        super(UpSampling1D, self).__init__((int(size),), 'channels_last', **kwargs)

    def call(self, inputs):
        output = K.repeat_elements(inputs, self.size[0], axis=1)
        return output

    def get_config(self):
        config = super(UpSampling1D, self).get_config()
        config['size'] = self.size[0]
        config.pop('data_format')
        return config


class UpSampling2D(_UpSampling):
    """Upsampling layer for 2D inputs.

    Repeats the rows and columns of the data
    by size[0] and size[1] respectively.

    # Arguments
        size: int, or tuple of 2 integers.
            The upsampling factors for rows and columns.
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, height, width, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, height, width)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
        interpolation: A string, one of `nearest` or `bilinear`.
            Note that CNTK does not support yet the `bilinear` upscaling
            and that with Theano, only `size=(2, 2)` is possible.

    # Input shape
        4D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, rows, cols, channels)`
        - If `data_format` is `"channels_first"`:
            `(batch, channels, rows, cols)`

    # Output shape
        4D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, upsampled_rows, upsampled_cols, channels)`
        - If `data_format` is `"channels_first"`:
            `(batch, channels, upsampled_rows, upsampled_cols)`
    """

    @interfaces.legacy_upsampling2d_support
    def __init__(self, size=(2, 2), data_format=None, interpolation='nearest',
                 **kwargs):
        normalized_size = conv_utils.normalize_tuple(size, 2, 'size')
        super(UpSampling2D, self).__init__(normalized_size, data_format, **kwargs)
        if interpolation not in ['nearest', 'bilinear']:
            raise ValueError('interpolation should be one '
                             'of "nearest" or "bilinear".')
        self.interpolation = interpolation

    def call(self, inputs):
        return K.resize_images(inputs, self.size[0], self.size[1],
                               self.data_format, self.interpolation)

    def get_config(self):
        config = super(UpSampling2D, self).get_config()
        config['interpolation'] = self.interpolation
        return config


class UpSampling3D(_UpSampling):
    """Upsampling layer for 3D inputs.

    Repeats the 1st, 2nd and 3rd dimensions
    of the data by size[0], size[1] and size[2] respectively.

    # Arguments
        size: int, or tuple of 3 integers.
            The upsampling factors for dim1, dim2 and dim3.
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, spatial_dim1, spatial_dim2, spatial_dim3, channels)`
            while `"channels_first"` corresponds to inputs with shape
            `(batch, channels, spatial_dim1, spatial_dim2, spatial_dim3)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".

    # Input shape
        5D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, dim1, dim2, dim3, channels)`
        - If `data_format` is `"channels_first"`:
            `(batch, channels, dim1, dim2, dim3)`

    # Output shape
        5D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, upsampled_dim1, upsampled_dim2, upsampled_dim3, channels)`
        - If `data_format` is `"channels_first"`:
            `(batch, channels, upsampled_dim1, upsampled_dim2, upsampled_dim3)`
    """

    @interfaces.legacy_upsampling3d_support
    def __init__(self, size=(2, 2, 2), data_format=None, **kwargs):
        normalized_size = conv_utils.normalize_tuple(size, 3, 'size')
        super(UpSampling3D, self).__init__(normalized_size, data_format, **kwargs)

    def call(self, inputs):
        return K.resize_volumes(inputs,
                                self.size[0], self.size[1], self.size[2],
                                self.data_format)


class _ZeroPadding(Layer):
    """Abstract nD ZeroPadding layer (private, used as implementation base).

    # Arguments
        padding: Tuple of tuples of two ints. Can be a tuple of ints when
            rank is 1.
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, ..., channels)` while `"channels_first"` corresponds to
            inputs with shape `(batch, channels, ...)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
    """
    def __init__(self, padding, data_format=None, **kwargs):
        # self.rank is 1 for ZeroPadding1D, 2 for ZeroPadding2D.
        self.rank = len(padding)
        self.padding = padding
        self.data_format = K.normalize_data_format(data_format)
        self.input_spec = InputSpec(ndim=self.rank + 2)
        super(_ZeroPadding, self).__init__(**kwargs)

    def call(self, inputs):
        raise NotImplementedError

    def compute_output_shape(self, input_shape):
        padding_all_dims = ((0, 0),) + self.padding + ((0, 0),)
        spatial_axes = list(range(1, 1 + self.rank))
        padding_all_dims = transpose_shape(padding_all_dims,
                                           self.data_format,
                                           spatial_axes)
        output_shape = list(input_shape)
        for dim in range(len(output_shape)):
            if output_shape[dim] is not None:
                output_shape[dim] += sum(padding_all_dims[dim])
        return tuple(output_shape)

    def get_config(self):
        config = {'padding': self.padding,
                  'data_format': self.data_format}
        base_config = super(_ZeroPadding, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))


class ZeroPadding1D(_ZeroPadding):
    """Zero-padding layer for 1D input (e.g. temporal sequence).

    # Arguments
        padding: int, or tuple of int (length 2), or dictionary.
            - If int:
            How many zeros to add at the beginning and end of
            the padding dimension (axis 1).
            - If tuple of int (length 2):
            How many zeros to add at the beginning and at the end of
            the padding dimension (`(left_pad, right_pad)`).

    # Input shape
        3D tensor with shape `(batch, axis_to_pad, features)`

    # Output shape
        3D tensor with shape `(batch, padded_axis, features)`
    """

    def __init__(self, padding=1, **kwargs):
        normalized_padding = (conv_utils.normalize_tuple(padding, 2, 'padding'),)
        super(ZeroPadding1D, self).__init__(normalized_padding,
                                            'channels_last',
                                            **kwargs)

    def call(self, inputs):
        return K.temporal_padding(inputs, padding=self.padding[0])

    def get_config(self):
        config = super(ZeroPadding1D, self).get_config()
        config['padding'] = config['padding'][0]
        config.pop('data_format')
        return config


class ZeroPadding2D(_ZeroPadding):
    """Zero-padding layer for 2D input (e.g. picture).

    This layer can add rows and columns of zeros
    at the top, bottom, left and right side of an image tensor.

    # Arguments
        padding: int, or tuple of 2 ints, or tuple of 2 tuples of 2 ints.
            - If int: the same symmetric padding
                is applied to height and width.
            - If tuple of 2 ints:
                interpreted as two different
                symmetric padding values for height and width:
                `(symmetric_height_pad, symmetric_width_pad)`.
            - If tuple of 2 tuples of 2 ints:
                interpreted as
                `((top_pad, bottom_pad), (left_pad, right_pad))`
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, height, width, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, height, width)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".

    # Input shape
        4D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, rows, cols, channels)`
        - If `data_format` is `"channels_first"`:
            `(batch, channels, rows, cols)`

    # Output shape
        4D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, padded_rows, padded_cols, channels)`
        - If `data_format` is `"channels_first"`:
            `(batch, channels, padded_rows, padded_cols)`
    """

    @interfaces.legacy_zeropadding2d_support
    def __init__(self,
                 padding=(1, 1),
                 data_format=None,
                 **kwargs):
        if isinstance(padding, int):
            normalized_padding = ((padding, padding), (padding, padding))
        elif hasattr(padding, '__len__'):
            if len(padding) != 2:
                raise ValueError('`padding` should have two elements. '
                                 'Found: ' + str(padding))
            height_padding = conv_utils.normalize_tuple(padding[0], 2,
                                                        '1st entry of padding')
            width_padding = conv_utils.normalize_tuple(padding[1], 2,
                                                       '2nd entry of padding')
            normalized_padding = (height_padding, width_padding)
        else:
            raise ValueError('`padding` should be either an int, '
                             'a tuple of 2 ints '
                             '(symmetric_height_pad, symmetric_width_pad), '
                             'or a tuple of 2 tuples of 2 ints '
                             '((top_pad, bottom_pad), (left_pad, right_pad)). '
                             'Found: ' + str(padding))
        super(ZeroPadding2D, self).__init__(normalized_padding,
                                            data_format,
                                            **kwargs)

    def call(self, inputs):
        return K.spatial_2d_padding(inputs,
                                    padding=self.padding,
                                    data_format=self.data_format)


class ZeroPadding3D(_ZeroPadding):
    """Zero-padding layer for 3D data (spatial or spatio-temporal).

    # Arguments
        padding: int, or tuple of 3 ints, or tuple of 3 tuples of 2 ints.
            - If int: the same symmetric padding
                is applied to height and width.
            - If tuple of 3 ints:
                interpreted as three different
                symmetric padding values for depth, height, and width:
                `(symmetric_dim1_pad, symmetric_dim2_pad, symmetric_dim3_pad)`.
            - If tuple of 3 tuples of 2 ints:
                interpreted as
                `((left_dim1_pad, right_dim1_pad),
                  (left_dim2_pad, right_dim2_pad),
                  (left_dim3_pad, right_dim3_pad))`
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, spatial_dim1, spatial_dim2, spatial_dim3, channels)`
            while `"channels_first"` corresponds to inputs with shape
            `(batch, channels, spatial_dim1, spatial_dim2, spatial_dim3)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".

    # Input shape
        5D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, first_axis_to_pad, second_axis_to_pad, third_axis_to_pad,
              depth)`
        - If `data_format` is `"channels_first"`:
            `(batch, depth,
              first_axis_to_pad, second_axis_to_pad, third_axis_to_pad)`

    # Output shape
        5D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, first_padded_axis, second_padded_axis, third_axis_to_pad,
              depth)`
        - If `data_format` is `"channels_first"`:
            `(batch, depth,
              first_padded_axis, second_padded_axis, third_axis_to_pad)`
    """

    @interfaces.legacy_zeropadding3d_support
    def __init__(self, padding=(1, 1, 1), data_format=None, **kwargs):
        if isinstance(padding, int):
            normalized_padding = 3 * ((padding, padding),)
        elif hasattr(padding, '__len__'):
            if len(padding) != 3:
                raise ValueError('`padding` should have 3 elements. '
                                 'Found: ' + str(padding))
            dim1_padding = conv_utils.normalize_tuple(padding[0], 2,
                                                      '1st entry of padding')
            dim2_padding = conv_utils.normalize_tuple(padding[1], 2,
                                                      '2nd entry of padding')
            dim3_padding = conv_utils.normalize_tuple(padding[2], 2,
                                                      '3rd entry of padding')
            normalized_padding = (dim1_padding, dim2_padding, dim3_padding)
        else:
            raise ValueError(
                '`padding` should be either an int, a tuple of 3 ints '
                '(symmetric_dim1_pad, symmetric_dim2_pad, symmetric_dim3_pad), '
                'or a tuple of 3 tuples of 2 ints '
                '((left_dim1_pad, right_dim1_pad),'
                ' (left_dim2_pad, right_dim2_pad),'
                ' (left_dim3_pad, right_dim2_pad)). '
                'Found: ' + str(padding))
        super(ZeroPadding3D, self).__init__(normalized_padding,
                                            data_format,
                                            **kwargs)

    def call(self, inputs):
        return K.spatial_3d_padding(inputs,
                                    padding=self.padding,
                                    data_format=self.data_format)


class CompactBilinearPooling(Layer):
    """Compact Bilinear Pooling
    TODO: Test this layer
    # Arguments
        d: dimension of the compact bilinear feature
        return_extra: return extra values
        conv_type: Type of convolution

    # Input shape
        2 modes
    # Output shape
        1 CBP
    # References
        - [Multimodal Compact Bilinear Pooling for Visual Question Answering and Visual Grounding](http://arxiv.org/pdf/1606.01847v2.pdf)
    """

    def __init__(self, d,
                 return_extra=False,
                 conv_type='conv',
                 **kwargs):
        self.h = [None, None]
        self.s = [None, None]
        self.return_extra = return_extra
        self.conv_type = conv_type
        self.d = d
        self.shape_in = None

        # layer parameters
        self.inbound_nodes = []
        self.outbound_nodes = []
        self.constraints = {}
        self.regularizers = []
        self.trainable_weights = []
        self.non_trainable_weights = []
        self.supports_masking = True
        self.trainable = False
        self.uses_learning_phase = False
        self.input_spec = None  # compatible with whatever
        super(CompactBilinearPooling, self).__init__(**kwargs)

    def build(self, input_shapes):
        self.trainable_weights = []
        self.nmodes = len(input_shapes)
        assert self.nmodes == 2
        self.shape_in = input_shapes
        for i in range(self.nmodes):
            if self.h[i] is None:
                self.h[i] = np.random.random_integers(0, self.d - 1, size=(input_shapes[i][1],))
                self.h[i] = K.variable(self.h[i], dtype='int64', name='h' + str(i))
            if self.s[i] is None:
                self.s[i] = (np.floor(np.random.uniform(0, 2, size=(input_shapes[i][1],))) * 2 - 1).astype('int64')
                self.s[i] = K.variable(self.s[i], dtype='int64', name='s' + str(i))
        self.non_trainable_weights = [self.h[i] for i in range(self.nmodes)] + [self.s[i] for i in range(self.nmodes)]

        self.built = True

    def compute_mask(self, input, input_mask=None):
        to_return = []
        if input_mask is None or not any([m is not None for m in input_mask]):
            to_return.append(None)
        else:
            to_return = input_mask[0]
        if self.return_extra:
            for i in range(self.nmodes):
                to_return += [None, None, None, None]
        return to_return  # +[None]

    def multimodal_compact_bilinear(self, x):
        v = [[]] * self.nmodes

        if self.conv_type == 'conv':
            for i in range(self.nmodes):
                v[i] = K.count_sketch(self.h[i], self.s[i], x[i], self.d)
            out = K.conv1d(v[0], v[1])

        elif self.conv_type == 'fft':
            raise NotImplementedError()
            fft_v = [[]] * self.nmodes
            acum_fft = 1.0
            for i in range(self.nmodes):
                '''
                v[i] = K.count_sketch(self.h[i], self.s[i], x[i], self.d)
                fft_v[i] = K.fft(v[i])
                acum_fft *= fft_v[i]
                '''
                v[i] = K.count_sketch(self.h[i], self.s[i], x[i], self.d)
                zeros_pad = K.zeros_like(v[i])[:, :-1]
                v_in = K.concatenate([zeros_pad,
                                      v[i],
                                      zeros_pad], axis=1)
                fft_v[i] = K.fft(v_in)
                prev = K.cast(K.floor(self.d / 2.), 'int16')
                post = K.cast(K.ceil(self.d / 2.), 'int16')
                acum_fft *= K.concatenate((fft_v[i][:, -post:], fft_v[i][:, :prev]), axis=1)

            out = K.cast(K.ifft(acum_fft), dtype='float32')

        else:
            raise NotImplementedError()

        if self.return_extra:
            # TODO: remove fft_v and acum_fft from all returns
            raise NotImplementedError("return_extra not implemented")
            return [out] + v + fft_v + [acum_fft]
        else:
            return out

    def call(self, x, mask=None):
        if type(x) is not list or len(x) < 2:
            raise Exception('CompactBilinearPooling must be called on a list of tensors '
                            '(at least 2). Got: ' + str(x))
        if len(self.shape_in[0]) > 2:
            x = [x[i].dimshuffle(tuple([0] + range(2, len(self.shape_in[0])) + [1])) for i in range(self.nmodes)]
            x = [K.reshape(x[i], tuple([-1] + [self.shape_in[0][1]])) for i in range(self.nmodes)]
            # x = [K.reshape(K.dimshuffle(x[i], tuple([0]+range(2,len(self.shape_in))+[1])), tuple([-1] + [self.shape_in[1]])) for i in range(self.nmodes)]
        y = self.multimodal_compact_bilinear(x)
        if len(self.shape_in[0]) > 2:
            y = K.reshape(y, tuple([-1] + self.shape_in[0][2:] + [self.d]))
            y.dimshuffle(tuple([0, -1] + range(1, len(self.shape_in[0]) - 1)))
            # y = K.dimshuffle(K.reshape(y, tuple([-1] + self.shape_in[0][2:] + [self.d])), tuple([0,-1]+range(1,len(self.shape_in)-1)))
        if self.return_extra:
            return y + self.h + self.s
        return y

    def get_config(self):
        config = {'d': self.d,
                  'return_extra': self.return_extra,
                  'conv_type': self.conv_type}
        base_config = super(CompactBilinearPooling, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))

    def get_output_shape_for(self, input_shape):
        assert type(input_shape) is list  # must have mutiple input shape tuples
        shapes = []
        shapes.append(tuple([input_shape[0][0], self.d] + list(input_shape[0][2:])))
        if self.return_extra:
            for s in input_shape:  # v
                shapes.append(tuple([np.prod(s[0] + list(s[2:])), self.d]))
            for s in input_shape:  # fft_v
                shapes.append(tuple([np.prod(s[0] + list(s[2:])), self.d]))
            shapes.append(tuple([np.prod(s[0] + list(s[2:])), self.d]))  # acum_fft
            for s in input_shape:  # h
                shapes.append(tuple([s[1], 1]))
            for s in input_shape:  # s
                shapes.append(tuple([s[1], 1]))
            return shapes
        else:
            return shapes[0]


class BilinearPooling(Layer):
    """Compact Bilinear Pooling
    TODO: Test this layer
    # Arguments
        d: dimension of the compact bilinear feature

    # Input shape
        2 modes
    # Output shape
        1 CBP
    # References
        - [Multimodal Compact Bilinear Pooling for Visual Question Answering and Visual Grounding](http://arxiv.org/pdf/1606.01847v2.pdf)
    """

    def __init__(self, d, **kwargs):
        # layer parameters
        self.inbound_nodes = []
        self.outbound_nodes = []
        self.constraints = {}
        self.regularizers = []
        self.trainable_weights = []
        self.non_trainable_weights = []
        self.supports_masking = True
        self.trainable = False
        self.uses_learning_phase = False
        self.input_spec = None  # compatible with whatever
        super(BilinearPooling, self).__init__(**kwargs)

    def build(self, input_shapes):
        self.trainable_weights = []
        self.nmodes = len(input_shapes)
        for i, s in enumerate(input_shapes):
            if s != input_shapes[0]:
                raise Exception('The input size of all vectors must be the same: '
                                'shape of vector on position ' + str(i) + ' (0-based) ' + str(s) + ' != shape of vector on position 0 ' + str(input_shapes[0]))
        self.built = True

    def compute_mask(self, input, input_mask=None):
        if input_mask is None or not any([m is not None for m in input_mask]):
            return None
        else:
            return input_mask[0]

    def multimodal_bilinear(self, x):
        v = [[]] * self.nmodes
        acum_fft = 1.0
        for i in range(self.nmodes):
            acum_fft = acum_fft * K.fft(x[i])
        return K.cast(K.ifft(acum_fft), dtype='float32')

    def call(self, x, mask=None):
        if type(x) is not list or len(x) <= 1:
            raise Exception('BilinearPooling must be called on a list of tensors '
                            '(at least 2). Got: ' + str(x))
        return self.multimodal_bilinear(x)

    def get_config(self):
        base_config = super(BilinearPooling, self).get_config()
        return dict(list(base_config.items()))

    def get_output_shape_for(self, input_shape):
        assert type(input_shape) is list  # must have mutiple input shape tuples
        return input_shape[0]


class CountSketch(Layer):

    """Count Sketch vector compacting
    TODO: Test this layer
    # Arguments
        d: dimension of the output compact representation
        return_extra: return extra values

    # Input shape
        2 modes
    # Output shape
        1 CBP
    # References
        - [Multimodal Compact Bilinear Pooling for Visual Question Answering and Visual Grounding](http://arxiv.org/pdf/1606.01847v2.pdf)
    """

    def __init__(self, d, return_extra=False, **kwargs):
        self.h = [None, None]
        self.s = [None, None]
        self.return_extra = return_extra
        self.d = d

        # layer parameters
        self.inbound_nodes = []
        self.outbound_nodes = []
        self.constraints = {}
        self.regularizers = []
        self.trainable_weights = []
        self.non_trainable_weights = []
        self.supports_masking = True
        self.trainable = False
        self.uses_learning_phase = False
        self.input_spec = None  # compatible with whatever
        self.built = False
        super(CountSketch, self).__init__(**kwargs)

    def build(self, input_shapes):
        if not self.built:
            self.trainable_weights = []
            self.nmodes = len(input_shapes)
            for i in range(self.nmodes):
                if self.h[i] is None:
                    self.h[i] = np.random.random_integers(0, self.d - 1, size=(input_shapes[i][1],))
                    self.h[i] = K.variable(self.h[i], dtype='int64', name='h' + str(i))
                if self.s[i] is None:
                    self.s[i] = (np.floor(np.random.uniform(0, 2, size=(input_shapes[i][1],))) * 2 - 1).astype('int64')
                    self.s[i] = K.variable(self.s[i], dtype='int64', name='s' + str(i))
        self.built = True

    def compute_mask(self, input, input_mask=None):
        to_return = []
        if input_mask is None or not any([m is not None for m in input_mask]):
            for i in range(len(input_mask)):
                to_return.append(None)
        else:
            to_return = input_mask
        if self.return_extra:
            for i in range(self.nmodes):
                to_return += [None, None]
        return to_return

    def compact(self, x):
        v = [[]] * self.nmodes
        for i in range(self.nmodes):
            v[i] = K.count_sketch(self.h[i], self.s[i], x[i], self.d)
        return v

    def call(self, x, mask=None):
        if type(x) is not list or len(x) <= 1:
            raise Exception('CountSketch must be called on a list of tensors.')
        y = self.compact(x)
        if self.return_extra:
            return y + self.h + self.s
        return y

    def get_config(self):
        config = {'d': self.d,
                  'return_extra': self.return_extra}
        base_config = super(CountSketch, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))

    def get_output_shape_for(self, input_shape):
        assert type(input_shape) is list  # must have mutiple input shape tuples
        shapes = []
        for s in input_shape:
            shapes.append(tuple([s[0], self.d]))
        if self.return_extra:
            for i in range(self.nmodes):
                shapes.append(tuple([input_shape[i][1], 1]))
            for i in range(self.nmodes):
                shapes.append(tuple([input_shape[i][1], 1]))
        return shapes


class _Cropping(Layer):
    """Abstract nD copping layer (private, used as implementation base).

    # Arguments
        cropping: A tuple of tuples of 2 ints.
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, ..., channels)` while `"channels_first"` corresponds to
            inputs with shape `(batch, channels, ...)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".
            For Cropping1D, the data format is always `"channels_last"`.
    """

    def __init__(self, cropping,
                 data_format=None,
                 **kwargs):
        super(_Cropping, self).__init__(**kwargs)
        # self.rank is 1 for Cropping1D, 2 for Cropping2D...
        self.rank = len(cropping)
        self.cropping = cropping
        self.data_format = K.normalize_data_format(data_format)
        self.input_spec = InputSpec(ndim=2 + self.rank)

    def call(self, inputs):
        slices_dims = []
        for start, end in self.cropping:
            if end == 0:
                end = None
            else:
                end = -end
            slices_dims.append(slice(start, end))

        slices = [slice(None)] + slices_dims + [slice(None)]
        slices = tuple(slices)
        spatial_axes = list(range(1, 1 + self.rank))
        slices = transpose_shape(slices, self.data_format, spatial_axes)
        return inputs[slices]

    def compute_output_shape(self, input_shape):
        cropping_all_dims = ((0, 0),) + self.cropping + ((0, 0),)
        spatial_axes = list(range(1, 1 + self.rank))
        cropping_all_dims = transpose_shape(cropping_all_dims,
                                            self.data_format,
                                            spatial_axes)
        output_shape = list(input_shape)
        for dim in range(len(output_shape)):
            if output_shape[dim] is not None:
                output_shape[dim] -= sum(cropping_all_dims[dim])
        return tuple(output_shape)

    def get_config(self):
        config = {'cropping': self.cropping,
                  'data_format': self.data_format}
        base_config = super(_Cropping, self).get_config()
        return dict(list(base_config.items()) + list(config.items()))


class Cropping1D(_Cropping):
    """Cropping layer for 1D input (e.g. temporal sequence).

    It crops along the time dimension (axis 1).

    # Arguments
        cropping: int or tuple of int (length 2)
            How many units should be trimmed off at the beginning and end of
            the cropping dimension (axis 1).
            If a single int is provided,
            the same value will be used for both.

    # Input shape
        3D tensor with shape `(batch, axis_to_crop, features)`

    # Output shape
        3D tensor with shape `(batch, cropped_axis, features)`
    """

    def __init__(self, cropping=(1, 1), **kwargs):
        normalized_cropping = (conv_utils.normalize_tuple(cropping, 2, 'cropping'),)
        super(Cropping1D, self).__init__(normalized_cropping,
                                         'channels_last',
                                         **kwargs)

    def get_config(self):
        base_config = super(Cropping1D, self).get_config()
        base_config.pop('data_format')
        base_config['cropping'] = base_config['cropping'][0]
        return base_config


class Cropping2D(_Cropping):
    """Cropping layer for 2D input (e.g. picture).

    It crops along spatial dimensions, i.e. height and width.

    # Arguments
        cropping: int, or tuple of 2 ints, or tuple of 2 tuples of 2 ints.
            - If int: the same symmetric cropping
                is applied to height and width.
            - If tuple of 2 ints:
                interpreted as two different
                symmetric cropping values for height and width:
                `(symmetric_height_crop, symmetric_width_crop)`.
            - If tuple of 2 tuples of 2 ints:
                interpreted as
                `((top_crop, bottom_crop), (left_crop, right_crop))`
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, height, width, channels)` while `"channels_first"`
            corresponds to inputs with shape
            `(batch, channels, height, width)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".

    # Input shape
        4D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, rows, cols, channels)`
        - If `data_format` is `"channels_first"`:
            `(batch, channels, rows, cols)`

    # Output shape
        4D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, cropped_rows, cropped_cols, channels)`
        - If `data_format` is `"channels_first"`:
            `(batch, channels, cropped_rows, cropped_cols)`

    # Examples

    ```python
        # Crop the input 2D images or feature maps
        model = Sequential()
        model.add(Cropping2D(cropping=((2, 2), (4, 4)),
                             input_shape=(28, 28, 3)))
        # now model.output_shape == (None, 24, 20, 3)
        model.add(Conv2D(64, (3, 3), padding='same'))
        model.add(Cropping2D(cropping=((2, 2), (2, 2))))
        # now model.output_shape == (None, 20, 16, 64)
    ```
    """

    @interfaces.legacy_cropping2d_support
    def __init__(self, cropping=((0, 0), (0, 0)),
                 data_format=None, **kwargs):
        if isinstance(cropping, int):
            normalized_cropping = ((cropping, cropping), (cropping, cropping))
        elif hasattr(cropping, '__len__'):
            if len(cropping) != 2:
                raise ValueError('`cropping` should have two elements. '
                                 'Found: ' + str(cropping))
            height_cropping = conv_utils.normalize_tuple(
                cropping[0], 2,
                '1st entry of cropping')
            width_cropping = conv_utils.normalize_tuple(
                cropping[1], 2,
                '2nd entry of cropping')
            normalized_cropping = (height_cropping, width_cropping)
        else:
            raise ValueError('`cropping` should be either an int, '
                             'a tuple of 2 ints '
                             '(symmetric_height_crop, symmetric_width_crop), '
                             'or a tuple of 2 tuples of 2 ints '
                             '((top_crop, bottom_crop), (left_crop, right_crop)). '
                             'Found: ' + str(cropping))
        super(Cropping2D, self).__init__(normalized_cropping,
                                         data_format,
                                         **kwargs)


class Cropping3D(_Cropping):
    """Cropping layer for 3D data (e.g. spatial or spatio-temporal).

    # Arguments
        cropping: int, or tuple of 3 ints, or tuple of 3 tuples of 2 ints.
            - If int: the same symmetric cropping
                is applied to depth, height, and width.
            - If tuple of 3 ints:
                interpreted as three different
                symmetric cropping values for depth, height, and width:
                `(symmetric_dim1_crop, symmetric_dim2_crop, symmetric_dim3_crop)`.
            - If tuple of 3 tuples of 2 ints:
                interpreted as
                `((left_dim1_crop, right_dim1_crop),
                  (left_dim2_crop, right_dim2_crop),
                  (left_dim3_crop, right_dim3_crop))`
        data_format: A string,
            one of `"channels_last"` or `"channels_first"`.
            The ordering of the dimensions in the inputs.
            `"channels_last"` corresponds to inputs with shape
            `(batch, spatial_dim1, spatial_dim2, spatial_dim3, channels)`
            while `"channels_first"` corresponds to inputs with shape
            `(batch, channels, spatial_dim1, spatial_dim2, spatial_dim3)`.
            It defaults to the `image_data_format` value found in your
            Keras config file at `~/.keras/keras.json`.
            If you never set it, then it will be "channels_last".

    # Input shape
        5D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, first_axis_to_crop, second_axis_to_crop, third_axis_to_crop,
              depth)`
        - If `data_format` is `"channels_first"`:
            `(batch, depth,
              first_axis_to_crop, second_axis_to_crop, third_axis_to_crop)`

    # Output shape
        5D tensor with shape:
        - If `data_format` is `"channels_last"`:
            `(batch, first_cropped_axis, second_cropped_axis, third_cropped_axis,
              depth)`
        - If `data_format` is `"channels_first"`:
            `(batch, depth,
              first_cropped_axis, second_cropped_axis, third_cropped_axis)`
    """

    @interfaces.legacy_cropping3d_support
    def __init__(self, cropping=((1, 1), (1, 1), (1, 1)),
                 data_format=None, **kwargs):
        self.data_format = K.normalize_data_format(data_format)
        if isinstance(cropping, int):
            normalized_cropping = ((cropping, cropping),
                                   (cropping, cropping),
                                   (cropping, cropping))
        elif hasattr(cropping, '__len__'):
            if len(cropping) != 3:
                raise ValueError('`cropping` should have 3 elements. '
                                 'Found: ' + str(cropping))
            dim1_cropping = conv_utils.normalize_tuple(cropping[0], 2,
                                                       '1st entry of cropping')
            dim2_cropping = conv_utils.normalize_tuple(cropping[1], 2,
                                                       '2nd entry of cropping')
            dim3_cropping = conv_utils.normalize_tuple(cropping[2], 2,
                                                       '3rd entry of cropping')
            normalized_cropping = (dim1_cropping, dim2_cropping, dim3_cropping)
        else:
            raise ValueError(
                '`cropping` should be either an int, a tuple of 3 ints '
                '(symmetric_dim1_crop, symmetric_dim2_crop, symmetric_dim3_crop), '
                'or a tuple of 3 tuples of 2 ints '
                '((left_dim1_crop, right_dim1_crop),'
                ' (left_dim2_crop, right_dim2_crop),'
                ' (left_dim3_crop, right_dim2_crop)). '
                'Found: ' + str(cropping))
        super(Cropping3D, self).__init__(normalized_cropping,
                                         data_format,
                                         **kwargs)


# Aliases

Convolution1D = Conv1D
Convolution2D = Conv2D
Convolution3D = Conv3D
SeparableConvolution1D = SeparableConv1D
SeparableConvolution2D = SeparableConv2D
Convolution2DTranspose = Conv2DTranspose
Deconvolution2D = Deconv2D = Conv2DTranspose
Deconvolution3D = Deconv3D = Conv3DTranspose

# Legacy aliases
AtrousConv1D = AtrousConvolution1D
AtrousConv2D = AtrousConvolution2D
