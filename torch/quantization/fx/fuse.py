from torch.fx import (
    GraphModule,
    map_arg
)

from torch.fx.graph import Graph

from .pattern_utils import (
    is_match,
    get_default_fusion_patterns,
)

from .fusion_patterns import *  # noqa: F401

class Fuser:
    def fuse(self, model, fuse_custom_config_dict=None):
        if fuse_custom_config_dict is None:
            fuse_custom_config_dict = {}

        input_root = model
        input_graph = model.graph
        self.modules = dict(input_root.named_modules())

        additional_fusion_patterns = fuse_custom_config_dict.get("additional_quant_pattern", {})
        fusion_patterns = get_default_fusion_patterns().copy()
        for k, v in additional_fusion_patterns.items():
            fusion_patterns[k] = v
        # find fusion
        fusion_pairs = self._find_matches(input_root, input_graph, fusion_patterns)
        self.fused_graph = Graph()
        env = {}

        def load_arg(a):
            return map_arg(a, lambda node: env[node.name])

        for node in input_graph.nodes:
            root_node, obj = fusion_pairs.get(node.name, (None, None))
            if root_node is node:
                env[node.name] = obj.fuse(self, load_arg)
            elif root_node is None:
                env[node.name] = self.fused_graph.node_copy(node, load_arg)
            # node matched in patterns and is not root is removed here

        model = GraphModule(input_root, self.fused_graph)
        return model

    def _find_matches(self, root, graph, patterns):
        modules = dict(root.named_modules())
        match_map = {}  # node name -> (root_node, match_value?)

        def apply_match(pattern, node, match):
            if isinstance(pattern, tuple):
                s, *args = pattern
                apply_match(s, node, match)
                for subpattern, arg in zip(args, node.args):
                    apply_match(subpattern, arg, match)
            else:
                # the first pattern matches will take precedence
                if node.name not in match_map:
                    match_map[node.name] = match

        for node in reversed(graph.nodes):
            if node.name not in match_map:
                for pattern, value in patterns.items():
                    if is_match(modules, node, pattern):
                        apply_match(pattern, node, (node, value(self, node)))

        return match_map
