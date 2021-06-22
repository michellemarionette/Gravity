import os
import torch
import torch.optim as optim
import torch.nn as nn
import torchaudio
from torch.utils.data import DataLoader
import torch.autograd.profiler as profiler
from model import Generator, Discriminator
from utils import AudioFolder, gradient_penalty
import time
import copy
import math


class Train:
    def __init__(
        self,

        # Iteration
        restart_from_iter,
        iter_num,
        epochs,
        datadir,
        
        # Training
        batch_size,

        # Learning
        learning_rate,

        # Model        
        scale_factor,       
        depth,
        num_filters,
        start_size,
     
        # Setup
        num_channels,
        sample_rate,
        save_every,
        num_workers,
        device
    ):
        # Iteration
        self.restart_from_iter = restart_from_iter
        self.iter_num = iter_num
        self.epochs = epochs
        self.datadir = datadir
        
        # Training
        self.batch_size = batch_size
        
        # Learning
        self.learning_rate = learning_rate

        # Generator
        self.ema_beta = 0.999

        # Model
        self.z_dim = 512
        self.scale_factor = scale_factor
        self.depth = depth
        self.num_filters = num_filters
        self.kernel_size = 9
        self.stride = 1
        self.padding = 4
        self.dilation = 1
        self.start_size = start_size

        # Setup
        self.num_channels = num_channels
        self.sample_rate = sample_rate
        self.save_every = save_every
        self.num_workers = num_workers
        self.device = device
        
        # Initialization
        torch.backends.cudnn.benchmark = True
        self.mean_path_length = 0

        self._init_models()
        self._init_optim()

        if self.restart_from_iter == True:
            self._load_state()
        else:
            self.start_epoch = 1
        
        # Creates a shadow copy of the generator.
        self.netG_shadow = copy.deepcopy(self.netG)

        # Initialize the generator shadow weights equal to generator.
        self._update_average(beta = 0)

        self.dataset = AudioFolder(self.datadir)
        self._training_loop()


# ------------------------------------------------------------
# Initialization functions.

    def _init_models(self):
        self.netG = Generator(
            z_dim = self.z_dim,
            nf = self.num_filters,
            kernel_size = self.kernel_size,
            stride = self.stride,
            padding = self.padding,
            dilation = self.dilation,
            depth = self.depth,
            num_channels = self.num_channels,
            scale_factor = self.scale_factor,
            start_size = self.start_size
        ).to(self.device)
        
        self.netD = Discriminator(
            nf = self.num_filters // (2 ** self.depth),
            kernel_size = self.kernel_size,
            stride = self.stride,
            padding = self.padding,
            dilation = self.dilation,
            depth = self.depth,
            num_channels = self.num_channels,
            scale_factor = 1 / self.scale_factor,
            start_size = self.start_size,
        ).to(self.device)


    def _init_optim(self): 
        self.opt_gen = optim.Adam(
            [
                {'params': self.netG.parameters()}
            ],
            lr = self.learning_rate,
            betas = (0.0, 0.99),
            eps = 1e-8
        )
        
        self.opt_dis = optim.Adam(
            params = self.netD.parameters(),
            lr = self.learning_rate, 
            betas = (0.0, 0.99),
            eps = 1e-8
        )

# ------------------------------------------------------------
# Model state functions.

    def _load_state(self):
        self._get_checkpoint()
        checkpointG = torch.load(
            'runs/iter_{iter_num}/model/checkpoint_{epoch}_G.pth.tar'.format(
                iter_num = self.iter_num,
                epoch = str(self.start_epoch).zfill(3)
            )
        )
        checkpointD = torch.load(
            'runs/iter_{iter_num}/model/checkpoint_{epoch}_D.pth.tar'.format(
                iter_num = self.iter_num,
                epoch = str(self.start_epoch).zfill(3)
            )
        )

        self.opt_gen.load_state_dict(checkpointG['optimizer'])
        self.opt_dis.load_state_dict(checkpointD['optimizer'])

        self.netG.load_state_dict(checkpointG['state_dict'])
        self.netD.load_state_dict(checkpointD['state_dict'])

    def _save_state(self, epoch): 
        checkpointD = {'state_dict': self.netD.state_dict(), 'optimizer': self.opt_dis.state_dict()}
        checkpointG = {'state_dict': self.netG.state_dict(), 'optimizer': self.opt_gen.state_dict()}    
        
        torch.save(checkpointD,
            'runs/iter_{iter_num}/model/checkpoint_{epoch}_D.pth.tar'.format(
                iter_num = self.iter_num,
                epoch = str(epoch).zfill(3)
            )
        )        
        torch.save(checkpointG,
            'runs/iter_{iter_num}/model/checkpoint_{epoch}_G.pth.tar'.format(
                iter_num = self.iter_num,
                epoch = str(epoch).zfill(3)
            )
        )
        

    def _get_checkpoint(self):
        models = os.listdir('runs/iter_{}/model/'.format(self.iter_num))

        start = 0
        for model in models:
            if int(model.split("_")[1]) > start:
                start = int(model.split("_")[1])

        self.start_epoch = start

# ------------------------------------------------------------
# Model training functions.

    def _training_loop(self):
        dataloader = DataLoader(
            self.dataset,
            batch_size = self.batch_size,
            shuffle = True,
            num_workers = self.num_workers,
            drop_last = True
        )

        for epoch in range(self.start_epoch, self.epochs + 1):
            start_time = time.time()

            # Save State
            if epoch % self.save_every == 0:
                self._save_state(epoch)

            # Prepare Data
                for idx, data in enumerate(dataloader):
                    real = data[0].to(self.device)

                    self._train_discriminator(real, idx)
                    self._train_generator(idx)
                    
                    self._update_average(beta = self.ema_beta)
                    
                    # Log State
                    print(
                        f'Epoch [{epoch}/{self.epochs}] \
                        Batch {idx} / {len(dataloader)} \
                        Loss D: {self.loss_disc:.4f}, loss G: {self.loss_gen:.4f}'
                    )

                    self._print_examples(idx, epoch, real)
        
            print("Time elapsed: ", int(time.time() - start_time), " seconds.")




    def _train_discriminator(self, real, idx):
        self.netD.zero_grad()

        self._set_grad_flag(self.netD, True)
        self._set_grad_flag(self.netG, False)

        real.requires_grad = True
        
        # Train on real samples.
        disc_real = self.netD(real).reshape(-1)
        disc_real = nn.functional.softplus(-disc_real).mean()
        disc_real.backward(retain_graph = True)
        
        # Train on fake samples.
        noise = torch.randn((self.batch_size, self.z_dim)).to(self.device)
        fake = self.netG(noise)
        disc_fake = self.netD(fake).reshape(-1)

        disc_fake = nn.functional.softplus(disc_fake).mean()
        disc_fake.backward()

        self.loss_disc = (disc_real + disc_fake) / 2     
        
        # R1.
        if idx % 16 == 0:
            grad_real = torch.autograd.grad(outputs = disc_real.sum(), inputs = real, create_graph = True)[0]
            grad_penalty_real = (grad_real.view(grad_real.size(0), -1).norm(2, dim=1) ** 2).mean()
            grad_penalty_real = 10 / 2 * grad_penalty_real

            grad_penalty_real.backward()
        
        self.opt_dis.step()
       


    def _train_generator(self, idx):
        self.netG.zero_grad()

        self._set_grad_flag(self.netD, False)
        self._set_grad_flag(self.netG, True)

        noise = torch.randn((self.batch_size, self.z_dim)).to(self.device)
        fake = self.netG(noise)
        output = self.netD(fake).reshape(-1)

        output = nn.functional.softplus(-output).mean()
        output.backward()
        
        self.loss_gen = output

        self.opt_gen.step()

        if idx % 8 == 0:
            path_batch_size = max(1, self.batch_size // 2)
            noise = torch.randn((self.batch_size, self.z_dim)).to(self.device)
            fake, latents = self.netG(noise, return_w = True)

            noise = torch.randn_like(fake) / math.sqrt(fake.shape[2])
            grad, = torch.autograd.grad(outputs = (fake * noise).sum(), inputs = latents, create_graph = True)

            path_lengths = torch.sqrt(grad.pow(2).sum(2).mean(1))
            path_mean = self.mean_path_length + 0.01 * (path_lengths.mean() - self.mean_path_length)
            path_loss = (path_lengths - path_mean).pow(2).mean()
            self.mean_path_length = path_mean.detach()

            self.netG.zero_grad()

            weighted_path_loss = 2 * 8 * path_loss
            weighted_path_loss += 0 * fake[0, 0, 0]
            weighted_path_loss.backward()

            self.opt_gen.step()




    """
    def _train_discriminator(self, real):
        noise = torch.randn((self.batch_size, self.z_dim)).to(self.device)
        fake = self.netG(noise)
                    
        disc_real = self.netD(real).reshape(-1)
        disc_fake = self.netD(fake).reshape(-1)
        
        gp = gradient_penalty(self.netD, real, fake, device = self.device)

        self.loss_disc = -(torch.mean(disc_real) - torch.mean(disc_fake)) + 10 * gp

        self.netD.zero_grad()
        self.loss_disc.backward(retain_graph = True)
        self.opt_dis.step()


    def _train_generator(self): 
        noise = torch.randn((self.batch_size, self.z_dim)).to(self.device)
        fake = self.netG(noise)
        output = self.netD(fake).reshape(-1)
        
        self.loss_gen = -torch.mean(output)
        
        self.netG.zero_grad()
        self.loss_gen.backward()
        self.opt_gen.step()
    """


# ------------------------------------------------------------
# Helper functions.

    def _print_examples(self, idx, epoch, real): 
        if idx % 1000 == 0:

            #REMOVE THIS
            self._save_state(epoch)
            
            with torch.no_grad():
                fake_sample = self.netG(
                    torch.randn((8, self.z_dim)).to(self.device),
                    self.depth
                )
                for s in range(8):
                    # Print Fake Examples
                    torchaudio.save(
                        filepath = 'runs/iter_' + str(self.iter_num) + '/output/fake/' + '_' + str(epoch).zfill(3) + '_' + str(s).zfill(3) + '.wav',
                        src = fake_sample[s].cpu(),
                        sample_rate = self.sample_rate
                    )

                """# Print Real Examples
                torchaudio.save(
                    filepath = 'runs/iter_' + str(self.iter_num) + '/output/real/' + '_' + str(epoch).zfill(3) + '_' + str(s).zfill(3) + '.wav',
                    src = real[s].cpu(),
                    sample_rate = self.sample_rate
                )"""

# ------------------------------------------------------------
# Update exponential moving average of generator.

    def _update_average(self, beta):
        # utility function for toggling the gradient requirements of the models
        def toggle_grad(model, requires_grad):
            for p in model.parameters():
                p.requires_grad_(requires_grad)

        # turn off gradient calculation
        toggle_grad(self.netG_shadow, False)
        toggle_grad(self.netG, False)

        param_dict_src = dict(self.netG.named_parameters())

        for p_name, p_tgt in self.netG_shadow.named_parameters():
            p_src = param_dict_src[p_name]
            assert (p_src is not p_tgt)
            p_tgt.copy_(beta * p_tgt + (1. - beta) * p_src)

        # turn back on the gradient calculation
        toggle_grad(self.netG_shadow, True)
        toggle_grad(self.netG, True)

    def _set_grad_flag(self, module, flag):
        for p in module.parameters():
            p.requires_grad = flag
