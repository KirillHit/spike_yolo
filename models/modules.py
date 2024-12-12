import torch
from torch import nn
import torch.nn.functional as F
from typing import List, Tuple, Dict
from norse.torch.utils.state import _is_module_stateful
import norse.torch as snn

__all__ = (
    "SumPool2d",
    "Storage",
    "LayerGen",
    "ListGen",
    "ListState",
    "Pass",
    "Conv",
    "Norm",
    "LIF",
    "Pool",
    "Return",
    "BlockGen",
    "ModelGen",
)


#####################################################################
#                          Custom modules                           #
#####################################################################


class SumPool2d(nn.Module):
    def __init__(self, kernel_size: int, stride: int = 1, padding: int = 0):
        super().__init__()
        self.kernel_size, self.stride, self.padding = kernel_size, stride, padding

    def forward(self, X):
        return (
            F.avg_pool2d(X, self.kernel_size, self.stride, self.padding)
            * self.kernel_size
            * self.kernel_size
        )


class Storage(nn.Module):
    """
    Stores the forward pass values. The "get" method returns the stored tensor.
    It is intended for use in feature pyramids, where you need to get multiple
    matrices from different places in the network.
    """

    storage: torch.Tensor

    def forward(self, X):
        self.storage = X
        return X

    def get_storage(self):
        return self.storage


#####################################################################
#                         Layer Generators                          #
#####################################################################


class LayerGen:
    def get(self, in_channels: int) -> Tuple[nn.Module, int]:
        raise NotImplementedError


type ListGen = List[LayerGen | ListGen]
type ListState = List[torch.Tensor | None | ListState]


class Pass(LayerGen):
    def get(self, in_channels: int) -> Tuple[nn.Module, int]:
        return nn.Identity, in_channels


class Conv(LayerGen):
    def __init__(self, out_channels: int, kernel_size: int = 3, stride: int = 1):
        self.out_channels = out_channels
        self.kernel_size = kernel_size
        self.stride = stride

    def get(self, in_channels: int) -> Tuple[nn.Module, int]:
        return nn.Conv2d(
            in_channels,
            self.out_channels,
            kernel_size=self.kernel_size,
            padding=int(self.kernel_size / 2),
            stride=self.stride,
            bias=False,
        ), self.out_channels


class Pool(LayerGen):
    def __init__(self, type: str, kernel_size: int = 2, stride: int = 2):
        self.kernel_size = kernel_size
        self.stride = stride
        match type:
            case "A":
                self.pool = nn.AvgPool2d
            case "M":
                self.pool = nn.MaxPool2d
            case "S":
                self.pool = SumPool2d
            case _:
                raise ValueError(f'[ERROR]: Non-existent pool type "{type}"!')

    def get(self, in_channels: int) -> Tuple[nn.Module, int]:
        return self.pool(self.kernel_size, self.stride), in_channels


class Norm(LayerGen):
    def get(self, in_channels: int) -> Tuple[nn.Module, int]:
        norm_layer = nn.BatchNorm2d(in_channels)
        norm_layer.bias = None
        return norm_layer, in_channels


class LIF(LayerGen):
    def get(self, in_channels: int) -> Tuple[nn.Module, int]:
        return snn.LIFCell(), in_channels


class Return(LayerGen):
    def get(self, in_channels: int) -> Tuple[nn.Module, int]:
        return Storage(), in_channels


#####################################################################
#                         Block Generators                          #
#####################################################################


class BlockGen(nn.Module):
    """Network Structural Elements Generator"""

    out_channels: int

    def __init__(self, in_channels: int, cfgs: ListGen):
        """Takes as input two-dimensional arrays of layer generators.
        The inner dimensions are sequential, the outer ones are added together.
        Lists can include blocks from other two-dimensional lists.
        They will be considered recursively.

        Args:
            in_channels (int): Number of input channels
            cfgs (ListGen): Two-dimensional lists of layer generators
        """
        super().__init__()
        branch_list: List[nn.ModuleList] = []
        self.branch_state: List[List[bool]] = []
        for branch_cfg in cfgs:
            layer_list, state_layers, self.out_channels = self._make_branch(
                in_channels, branch_cfg
            )
            branch_list.append(layer_list)
            self.branch_state.append(state_layers)
        self.net = nn.ModuleList(branch_list)

    def _make_branch(
        self, in_channels: int, cfg: ListGen
    ) -> Tuple[nn.ModuleList, ListState, int]:
        """Recursively generates a network branch from a configuration list.
        Args:
            in_channels (int): Number of input channels
            cfg (ListGen): Lists of layer generators
        Returns:
            Tuple[nn.ModuleList, ListState, int]:
                0 - List of modules;
                1 - Mask of layers requiring states;
                2 - Number of output channels;
        """
        state_layers: List[bool] = []
        layer_list: List[nn.Module] = []
        channels = in_channels
        for layer_gen in cfg:
            if isinstance(layer_gen, list):
                layer = BlockGen(channels, layer_gen)
                channels = layer.out_channels
            else:
                layer, channels = layer_gen.get(channels)
            layer_list.append(layer)
            state_layers.append(_is_module_stateful(layer))
        return nn.ModuleList(layer_list), state_layers, channels

    def forward(
        self, X: torch.Tensor, state: ListState | None = None
    ) -> Tuple[torch.Tensor, ListState]:
        """
        Args:
            X (torch.Tensor): Input tensor. Shape is [batch, p, h, w].
            state (ListState, optional). Defaults to None.
        Returns:
            Tuple[torch.Tensor, ListState].
        """
        out = []
        out_state = []
        state = [None] * len(self.net) if state is None else state
        for branch, state_flags, branch_state in zip(
            self.net, self.branch_state, state
        ):
            branch_state = (
                [None] * len(branch) if branch_state is None else branch_state
            )
            Y = X
            for idx, (layer, is_state) in enumerate(zip(branch, state_flags)):
                if is_state:
                    Y, branch_state[idx] = layer(Y, branch_state[idx])
                else:
                    Y = layer(Y)
            out.append(Y)
            out_state.append(branch_state)
        return torch.stack(out).sum(dim=0), out_state


#####################################################################
#                        Backbone Generator                         #
#####################################################################


class ModelGen(nn.Module):
    out_channels: int = 0
    default_cfgs: Dict[str, ListGen] = {}

    def __init__(
        self,
        cfg: str | ListGen,
        in_channels=2,
        init_weights=False,
    ) -> None:
        super().__init__()

        self._load_cfg()

        self.net = BlockGen(
            in_channels, [cfg] if isinstance(cfg, list) else [self.default_cfgs[cfg]]
        )
        self.out_channels = self.net.out_channels

        if init_weights:
            for m in self.modules():
                if isinstance(m, nn.Conv2d):
                    nn.init.normal_(m.weight, mean=0.9, std=0.1)
                elif isinstance(m, nn.BatchNorm2d):
                    nn.init.constant_(m.weight, 1)

    def _load_cfg(self):
        raise NotImplementedError

    def forward_impl(self, X, state):
        raise NotImplementedError

    def forward(self, X):
        raise NotImplementedError
