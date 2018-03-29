#
# This code is an implementation of Trainable ISTA (TISTA) for sparse signal recovery in PyTorch.
# The details of the algorithm can be found in the paper:
# Daisuke Ito, Satoshi Takabe, Tadashi Wadayama,
# "Trainable ISTA for Sparse Signal Recovery", arXiv:1801.01978.
# (Computer experiments in the paper was performed with another TensorFlow implementation)
#
# GPU is required for execution of this program. If you do not have GPU, buy it or
# remove .cuda() from the following code.
#

import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F
import torch.optim as optim
import math
import time

# global variables

N = 500  # length of a source signal vector
M = 250  # length of a observation vector
p = 0.1  # probability for occurrence of non-zero components

batch_size = 100  # mini-batch size
num_batch = 200  # number of mini-batches in a generation
num_generations = 15  # number of generations
snr = 40.0  # SNR for the system in dB

alpha2 = 1.0  # variance of non-zero component
alpha_std = math.sqrt(alpha2)
max_layers = 20  # maximum number of layers
adam_lr = 0.04  # learning parameter for Adam

A = torch.normal(0.0, std=math.sqrt(1.0 / M) * torch.ones(M, N))  # sensing matrix
At = A.t()
W = At.mm((A.mm(At)).inverse())  # pseudo inverse matrix
Wt = W.t()

taa = (At.mm(A)).trace()  # trace(A^T A)
tww = (W.mm(Wt)).trace()  # trace(W W^T)

Wt = Variable(Wt).cuda()
At = Variable(At).cuda()

# detection for NaN
def isnan(x):
    return x != x

# mini-batch generator
def generate_batch():
    support = torch.bernoulli(p * torch.ones(batch_size, N))
    nonzero = torch.normal(0.0, alpha_std * torch.ones(batch_size, N))
    return torch.mul(nonzero, support)


# definition of TISTA network
class TISTA_NET(nn.Module): 
    def __init__(self):
        super(TISTA_NET, self).__init__() 
        self.gamma = nn.Parameter(torch.normal(1.0, 0.1*torch.ones(max_layers))) 

    def gauss(self, x,  var):
        return torch.exp(-torch.mul(x, x)/(2.0*var))

    def MMSE_shrinkage(self, y, tau2):  # MMSE shrinkage function
        return (y*alpha2/xi)*p*self.gauss(y, xi)/((1-p)*self.gauss(y, tau2) + p*self.gauss(y, xi))
        
    def eval_tau2(self, t, i):  # error variance estimator
        v2 = (t.norm(2,1).pow(2.0) - M*sigma2)/taa
        v2.clamp(min=1e-7)
        tau2 = (v2/N)*(N+(self.gamma[i]*self.gamma[i]-2.0*self.gamma[i])*M)+self.gamma[i]*self.gamma[i]*tww*sigma2/N
        tau2 = (tau2.expand(N, batch_size)).t()
        return tau2
        
    def forward(self, x, s, max_itr):  # TISTA network
        y = x.mm(At) + Variable(torch.normal(0.0, sigma_std*torch.ones(batch_size, M))).cuda()
        for i in range(max_itr):
            t = y - s.mm(At)
            tau2 = self.eval_tau2(t, i)
            r = s + t.mm(Wt)*self.gamma[i]
            s = self.MMSE_shrinkage(r, tau2)
        return s


def main():
    global sigma_std, sigma2, xi

    network = TISTA_NET().cuda()  # generating an instance of TISTA network
    s_zero = Variable(torch.zeros(batch_size, N)).cuda()  # initial value
    opt = optim.Adam(network.parameters(), lr=adam_lr)  # setting for optimizer (Adam)

    # SNR calculation
    sum = 0.0
    for i in range(100):
        x = Variable(generate_batch()).cuda()
        y = x.mm(At)
        sum += (y.norm(2, 1).pow(2.0)).sum().data[0]
    ave = sum/(100.0 * batch_size)
    sigma2 = ave/(M*math.pow(10.0, snr/10.0))
    sigma_std = math.sqrt(sigma2)
    xi = alpha2 + sigma2

    # incremental training loop
    torch.manual_seed(1)
    start = time.time()
    for gen in range(num_generations):
        for i in range(num_batch):
            x = Variable(generate_batch()).cuda()
            opt.zero_grad()
            x_hat = network(x, s_zero, gen+1).cuda()
            loss = F.mse_loss(x_hat, x)
            loss.backward()

            grads = torch.stack([param.grad for param in network.parameters()])
            if isnan(grads).any():  # avoiding NaN in gradients
                continue

            opt.step()

        # accuracy check
        nmse_sum = 0.0
        for i in range(10):
            x = Variable(generate_batch()).cuda()
            x_hat = network(x, s_zero, gen+1).cuda()
            num = (x - x_hat).norm(2, 1).pow(2.0)
            denom = x.norm(2,1).pow(2.0)
            nmse = 10.0*torch.log(num/denom)/math.log(10.0)
            nmse_sum += torch.sum(nmse).data[0]
        # print('(%d) NMSE= %.4f' % (gen + 1, nmse_sum / (10.0 * batch_size)))
        print('({0}) NMSE= {1:6.3f}'.format(gen + 1, nmse_sum / (10.0 * batch_size)))

    elapsed_time = time.time() - start
    print("elapsed_time:{0}".format(elapsed_time) + "[sec]")


if __name__ == '__main__':
    main()
