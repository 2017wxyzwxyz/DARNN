import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
import sys
import tensorflow as tf
import numpy as np
from tensorflow.contrib.legacy_seq2seq.python.ops import seq2seq
from tensorflow.contrib.rnn.python.ops import rnn
# from tensorflow.contrib.rnn.python.ops import core_rnn_cell_impl as rnn_cell  #omit when tf = 1.3
from tensorflow.python.ops import rnn_cell_impl as rnn_cell #add when tf = 1.3
import attention_encoder
import Generate_stock_data as GD
import pandas as pd
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' #Disable Tensorflow debugging message
gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.1)


def mean_absolute_percentage_error(y_true, y_pred): 
    """
    Use of this metric is not recommended; for illustration only. 
    See other regression metrics on sklearn docs:
      http://scikit-learn.org/stable/modules/classes.html#regression-metrics
    Use like any other metric
    >>> y_true = [3, -0.5, 2, 7]; y_pred = [2.5, -0.3, 2, 8]
    >>> mean_absolute_percentage_error(y_true, y_pred)
    Out[]: 24.791666666666668
    """

    # y_true, y_pred = check_arrays(y_true, y_pred)

    ## Note: does not handle mix 1d representation
    #if _is_1d(y_true): 
    #    y_true, y_pred = _check_1d_array(y_true, y_pred)

    return np.mean(np.abs((y_true - y_pred) / y_true)) * 100
    
from sklearn.metrics import mean_absolute_error
from sklearn.metrics import mean_squared_error

        
def RNN(encoder_input, decoder_input, weights, biases, encoder_attention_states, 
        n_input_encoder, n_steps_encoder, n_hidden_encoder,
        n_input_decoder, n_steps_decoder, n_hidden_decoder):

    # Prepare data shape to match `rnn` function requirements
    # Current data input shape: (batch_size, n_steps, n_input)
    # Required shape: 'n_steps' tensors list of shape (batch_size, n_input)

    # Prepare data for encoder
    # Permuting batch_size and n_steps
    encoder_input = tf.transpose(encoder_input, [1, 0, 2])
    # Reshaping to (n_steps*batch_size, n_input)
    encoder_input = tf.reshape(encoder_input, [-1, n_input_encoder])
    # Split to get a list of 'n_steps' tensors of shape (batch_size, n_input)
    encoder_input = tf.split(encoder_input, n_steps_encoder, 0)

    # Prepare data for decoder
    # Permuting batch_size and n_steps
    decoder_input = tf.transpose(decoder_input, [1, 0, 2])
    # Reshaping to (n_steps*batch_size, n_input)
    decoder_input = tf.reshape(decoder_input, [-1, n_input_decoder])
    # Split to get a list of 'n_steps' tensors of shape (batch_size, n_input)
    decoder_input = tf.split(decoder_input, n_steps_decoder,0 )

    # Encoder.
    with tf.variable_scope('encoder') as scope:
        encoder_cell = rnn_cell.BasicLSTMCell(n_hidden_encoder, forget_bias=1.0)
        encoder_outputs, encoder_state, attn_weights = attention_encoder.attention_encoder(encoder_input,
                                         encoder_attention_states, encoder_cell)

    # First calculate a concatenation of encoder outputs to put attention on.
    top_states = [tf.reshape(e, [-1, 1, encoder_cell.output_size]) for e in encoder_outputs]
    attention_states = tf.concat(top_states,1)

    with tf.variable_scope('decoder') as scope:
        decoder_cell = rnn_cell.BasicLSTMCell(n_hidden_decoder, forget_bias=1.0)
        outputs, states = seq2seq.attention_decoder(decoder_input, encoder_state,
                                            attention_states, decoder_cell)

    return tf.matmul(outputs[-1], weights['out1']) + biases['out1'], attn_weights


def run(timestep, n_hidden, horizon):
    all_pred_val = []
    all_test_val = []

    tf.reset_default_graph()
    # Parameters
    learning_rate = 0.001
    training_iters = 1000000
    batch_size  = 128

    model_path = './model/'
    filename = sys.argv[1]

    df= pd.read_csv(filename)
    if 'spx' in sys.argv[1]:
        df.drop(columns=['key'], inplace=True)
    display_step = int(df.shape[0]*.8)//batch_size

    # Network Parameters
    # encoder parameter
    num_feature =  df.shape[1]-1 # number of index  #98 #72
    print(num_feature)
    n_input_encoder =  df.shape[1]-1 # n_feature of encoder input  #98 #72
    n_steps_encoder = timestep # time steps 
    # n_hidden_encoder = 256 # size of hidden units 
    n_hidden_encoder = n_hidden

    # decoder parameter
    n_input_decoder = 1
    n_steps_decoder = timestep
    # n_hidden_decoder = 256 
    n_hidden_decoder = n_hidden
    n_classes = 1 # size of the decoder output

    # tf Graph input
    encoder_input = tf.placeholder("float", [None, n_steps_encoder, n_input_encoder])
    decoder_input = tf.placeholder("float", [None, n_steps_decoder, n_input_decoder])
    decoder_gt = tf.placeholder("float", [None, n_classes])
    encoder_attention_states = tf.placeholder("float", [None, n_input_encoder, n_steps_encoder])

    # Define weights
    weights = {'out1': tf.Variable(tf.random_normal([n_hidden_decoder, n_classes]))}
    biases = {'out1': tf.Variable(tf.random_normal([n_classes]))}

    # pred, attn_weights = RNN(encoder_input, decoder_input, weights, biases, encoder_attention_states)

    pred, attn_weights = RNN(encoder_input, decoder_input, weights, biases, encoder_attention_states,
                             n_input_encoder, n_steps_encoder, n_hidden_encoder,
                             n_input_decoder, n_steps_decoder, n_hidden_decoder)

    # Define loss and optimizer
    cost = tf.reduce_sum(tf.pow(tf.subtract(pred, decoder_gt), 2))
    loss = tf.pow(tf.subtract(pred, decoder_gt), 2)
    optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate).minimize(cost)
    init = tf.global_variables_initializer()

    # save the model
    saver = tf.train.Saver()
    loss_value = []
    step_value = []
    loss_test=[]
    loss_val = []

# Launch the graph
    with tf.Session(config=tf.ConfigProto(gpu_options=gpu_options)) as sess:
        
        sess.run(init)
        def get_nb_params_shape(shape):
        # '''
        # Computes the total number of params for a given shap.
        # Works for any number of shapes etc [D,F] or [W,H,C] computes D*F and W*H*C.
        # '''
            nb_params = 1
            for dim in shape:
                nb_params = nb_params*int(dim)
            return nb_params 
        def count_number_trainable_params():
        # '''
        # Counts the number of trainable variables.
        # '''
            tot_nb_params = 0
            for trainable_variable in tf.trainable_variables():
                shape = trainable_variable.get_shape() # e.g [D,F] or [W,H,C]
                current_nb_params = get_nb_params_shape(shape)
                tot_nb_params = tot_nb_params + current_nb_params
            return tot_nb_params
        

        step = 1
        count = 1

        Data = GD.Input_data(batch_size, n_steps_encoder, n_steps_decoder, n_hidden_encoder, filename, n_classes, horizon)
        # Keep training until reach max iterations
        mn_validation_loss = 1e15
        while step  < training_iters:
            # the shape of batch_x is (batch_size, n_steps, n_input)

            sz = Data.train.shape[0]//batch_size
            all_batch_x, all_batch_y, all_prev_y, all_encoder_states = Data.next_batch()
            for i in range(sz):

                batch_x = all_batch_x[batch_size*i: batch_size*(i+1), ...]
                batch_y = all_batch_y[batch_size*i: batch_size*(i+1), ...]
                prev_y = all_prev_y[batch_size*i: batch_size*(i+1), ...]
                encoder_states = all_encoder_states[batch_size*i: batch_size*(i+1), ...]

                feed_dict = {encoder_input: batch_x, decoder_gt: batch_y, decoder_input: prev_y,
                            encoder_attention_states:encoder_states}
                # Run optimization op (backprop)
                sess.run(optimizer, feed_dict)

                step += 1
                count += 1

                # reduce the learning rate
                if count > 10000:
                    learning_rate *= 0.1
                    count = 0
                    save_path = saver.save(sess, model_path  + 'dual_stage_' + str(step) + '.ckpt')

            # display the result
            if True:
                # Calculate batch loss
                loss = sess.run(cost, feed_dict)/batch_size
                epoch = step // display_step
                if epoch  > 50:
                    break
                print "Epoch", epoch
                print "Iter " + str(step) + ", Minibatch Loss= " + "{:.6f}".format(loss)

                #store the value
                loss_value.append(loss)
                step_value.append(step)

                # Val
                val_x, val_y, val_prev_y, encoder_states_val = Data.validation()
                feed_dict = {encoder_input: val_x, decoder_gt: val_y, decoder_input: val_prev_y,
                            encoder_attention_states:encoder_states_val}
                loss_val1 = sess.run(cost, feed_dict)/len(val_y)
                loss_val.append(loss_val1)
                print "validation loss:", loss_val1

                # testing
                test_x, test_y, test_prev_y, encoder_states_test= Data.testing()
                feed_dict = {encoder_input: test_x, decoder_gt: test_y, decoder_input: test_prev_y,
                            encoder_attention_states:encoder_states_test}
                pred_y=sess.run(pred, feed_dict)
                loss_test1 = sess.run(cost, feed_dict)/len(test_y)
                loss_test.append(loss_test1)
                print "Testing loss:", loss_test1


                mean, stdev = Data.returnMean()
                # print mean
                # print stdev

                testing_result = test_y*stdev[num_feature] + mean[num_feature]
                pred_result = pred_y*stdev[num_feature] + mean[num_feature]
                
                all_test_val.append(str(testing_result[len(testing_result) - 1]).replace('[', '').replace(']', ''))
                all_pred_val.append(str(pred_result[len(pred_result) - 1]).replace('[', '').replace(']', ''))

                # print "testing data:"
                # print testing_result
                # print testing_result.shape

                # print "pred data:"
                # print pred_result
                # print pred_result.shape
                # from sklearn.utils import check_arrays
                if loss_val1 < mn_validation_loss:
                    df = pd.DataFrame(pred_result, columns=['pred'])
                    df.insert(loc=1, column='gt', value=testing_result)
                    df.to_csv('gef_prediction.csv', index=False)

                    mn_validation_loss = loss_val1
                    mae = mean_absolute_error(testing_result, pred_result)
                    mse = mean_squared_error(testing_result, pred_result)
                    mape = mean_absolute_percentage_error(testing_result, pred_result)
                    print('mae', mae)
                    print('mse', mse)
                    print('mape', mape)


        print "Optimization Finished!"
        f.write('{},{},{},{},{},{}\n'.format(horizon,timestep, n_hidden, mae, mse, mape))
        f.flush()

if __name__ == '__main__':

    f = open(sys.argv[2], 'a+')
    f.write('horizon,timestep,n_hidden,mae,mse,mape\n')
    run(168, 32, 24)
    # run(168, 32, 3)
    for _ in range(10):
        # for timestep in [3, 5, 10, 15, 25]:
        for n_hidden in [16]:
            for horizon in [1,3, 6, 12, 24]:
            # for n_hidden in [16]:
                    f.flush()

    f.close()
