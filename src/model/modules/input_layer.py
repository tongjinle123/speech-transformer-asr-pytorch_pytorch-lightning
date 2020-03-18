import math
import torch
import torch.nn as nn
import torch as t
from src.model.modules.gelu import Gelu


class PositionalEncoding(nn.Module):
    """Positional encoding."""

    def __init__(self, d_model, dropout_rate, max_len=5000):
        """Initialize class.
        :param int d_model: embedding dim
        :param float dropout_rate: dropout rate
        :param int max_len: maximum input length
        """
        super(PositionalEncoding, self).__init__()
        self.d_model = d_model
        self.xscale = math.sqrt(self.d_model)
        self.dropout = nn.Dropout(p=dropout_rate)
        self.pe = None
        self.extend_pe(torch.tensor(0.0).expand(1, max_len))

    def extend_pe(self, x):
        """Reset the positional encodings."""
        if self.pe is not None:
            if self.pe.size(1) >= x.size(1):
                if self.pe.dtype != x.dtype or self.pe.device != x.device:
                    self.pe = self.pe.to(dtype=x.dtype, device=x.device)
                return
        pe = torch.zeros(x.size(1), self.d_model)
        position = torch.arange(0, x.size(1), dtype=torch.float32).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, self.d_model, 2, dtype=torch.float32) *
                             -(math.log(10000.0) / self.d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        self.pe = pe.to(device=x.device, dtype=x.dtype)

    def forward(self, x: torch.Tensor):
        """Add positional encoding.
        Args:
            x (torch.Tensor): Input. Its shape is (batch, time, ...)
        Returns:
            torch.Tensor: Encoded tensor. Its shape is (batch, time, ...)
        """
        self.extend_pe(x)
        x = x * self.xscale + self.pe[:, :x.size(1)]
        return self.dropout(x)


class ScaledPositionalEncoding(PositionalEncoding):
    """Scaled positional encoding module.
    See also: Sec. 3.2  https://arxiv.org/pdf/1809.08895.pdf
    """

    def __init__(self, d_model, dropout_rate, max_len=5000):
        """Initialize class.
        :param int d_model: embedding dim
        :param float dropout_rate: dropout rate
        :param int max_len: maximum input length
        """
        super().__init__(d_model=d_model, dropout_rate=dropout_rate, max_len=max_len)
        self.alpha = nn.Parameter(torch.tensor(1.0))

    def reset_parameters(self):
        """Reset parameters."""
        self.alpha.data = torch.tensor(1.0)

    def forward(self, x):
        """Add positional encoding.
        Args:
            x (torch.Tensor): Input. Its shape is (batch, time, ...)
        Returns:
            torch.Tensor: Encoded tensor. Its shape is (batch, time, ...)
        """
        self.extend_pe(x)
        x = x + self.alpha * self.pe[:, :x.size(1)]
        return self.dropout(x)


class Conv2dSubsampling(t.nn.Module):
    """Convolutional 2D subsampling (to 1/4 length)
    :param int idim: input dim
    :param int odim: output dim
    :param flaot dropout_rate: dropout rate
    """

    def __init__(self, idim, odim, dropout_rate):
        super(Conv2dSubsampling, self).__init__()
        self.conv = t.nn.Sequential(
            t.nn.Conv2d(1, odim, 3, 2),
            t.nn.ReLU(),
            t.nn.Conv2d(odim, odim, 3, 2),
            t.nn.ReLU()
        )
        self.out = t.nn.Sequential(
            t.nn.Linear(odim * (((idim - 1) // 2 - 1) // 2), odim),
            PositionalEncoding(odim, dropout_rate)
        )
        t.nn.init.kaiming_normal_(self.conv[0].weight)
        t.nn.init.kaiming_normal_(self.conv[2].weight)
        t.nn.init.zeros_(self.conv[0].bias)
        t.nn.init.zeros_(self.conv[2].bias)

    def forward(self, x, x_mask):
        """Subsample x
        :param torch.Tensor x: input tensor
        :param torch.Tensor x_mask: input mask
        :return: subsampled x and mask
        :rtype Tuple[torch.Tensor, torch.Tensor]
        """
        x = x.unsqueeze(1)  # (b, c, t, f)
        x = self.conv(x)
        b, c, t, f = x.size()
        x = self.out(x.transpose(1, 2).contiguous().view(b, t, c * f))
        if x_mask is None:
            return x, None
        return x, x_mask[:, :-2:2][:, :-2:2]


class LinearWithPosEmbedding(nn.Module):
    def __init__(self, input_size, d_model, dropout_rate=0.0):
        super(LinearWithPosEmbedding, self).__init__()
        self.linear = nn.Linear(input_size, d_model)
        self.pos_embedding = ScaledPositionalEncoding(d_model, dropout_rate)
        nn.init.xavier_normal_(self.linear.weight)

    def forward(self, inputs, mask):
        inputs = self.linear(inputs)
        inputs = self.pos_embedding(inputs)
        return inputs, mask


class Input_layer(t.nn.Module):
    def __init__(self, input_size, d_model, dropout_rate=0.0, layer_type='linear'):
        super(Input_layer, self).__init__()
        if layer_type == 'linear':
            self.core = LinearWithPosEmbedding(input_size, d_model, dropout_rate)
        else:
            self.core = Conv2dSubsampling(input_size, d_model, dropout_rate)

    def forward(self, inputs, mask):
        net, mask = self.core(inputs, mask)
        net.masked_fill_(~mask.unsqueeze(-1), 0.0)
        return net, mask


class LinearWithPosEmbedding2(nn.Module):
    def __init__(self, input_size, d_model, dropout_rate=0.0):
        super(LinearWithPosEmbedding2, self).__init__()
        self.linear = t.nn.Sequential(
            t.nn.Linear(input_size, d_model),
            t.nn.LayerNorm(d_model),
            t.nn.Dropout(dropout_rate),
            Gelu()
        )

        self.pos_embedding = ScaledPositionalEncoding(d_model, dropout_rate)
        nn.init.xavier_normal_(self.linear.weight)

    def forward(self, inputs, mask):
        inputs = self.linear(inputs)
        inputs = self.pos_embedding(inputs)
        return inputs, mask


class Input_layer2(t.nn.Module):
    def __init__(self, input_size, d_model, dropout_rate=0.0, layer_type='linear'):
        super(Input_layer2, self).__init__()
        if layer_type == 'linear':
            self.core = LinearWithPosEmbedding2(input_size, d_model, dropout_rate)
        else:
            self.core = Conv2dSubsampling(input_size, d_model, dropout_rate)

    def forward(self, inputs, mask):
        net, mask = self.core(inputs, mask)
        net.masked_fill_(~mask.unsqueeze(-1), 0.0)
        return net, mask
