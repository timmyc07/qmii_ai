"""Compile the two supplied editor graphs into reviewed, path-free API recipes.

Only the connected inference branches are exported. Editor routing and empty
LoRA/attention wrappers are replaced by equivalent native connections.
"""
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.runtime' / 'creation_library'
DESTINATION = ROOT / 'config' / 'chroma_workflows.json'


def read_graph(archive):
    with zipfile.ZipFile(SOURCE / archive) as stream:
        name = next(name for name in stream.namelist() if name.endswith('.json') and not name.startswith('__MACOSX'))
        value = json.loads(stream.read(name))
    return value


def compile_graph(editor, output, aliases, replacements):
    nodes = {node['id']: node for node in editor['nodes']}
    links = {link[0]: link for link in editor['links']}
    setters = {node['widgets_values'][0]: node for node in nodes.values() if node['type'] == 'easy setNode'}
    graph = {}
    visiting = set()

    def source(node, name=None):
        item = next(item for item in node.get('inputs', []) if (name is None or item['name'] == name) and item.get('link') is not None)
        link = links[item['link']]
        return resolve(link[1], link[2])

    def resolve(node_id, slot=0):
        if node_id in aliases:
            return resolve(*aliases[node_id])
        node = nodes[node_id]
        kind = node['type']
        if kind == 'easy getNode':
            return source(setters[node['widgets_values'][0]])
        if kind in ('easy setNode', 'Reroute', 'PathchSageAttentionKJ'):
            return source(node)
        if kind == 'Power Lora Loader (rgthree)':
            if any(isinstance(value, dict) and value.get('lora') for value in node.get('widgets_values', [])):
                raise ValueError('The reviewed template must not contain an implicit LoRA.')
            return source(node, 'model' if slot == 0 else 'clip')
        if kind == 'GetImageSize+':
            export(node_id)
            return [f'c{node_id}', slot]
        export(node_id)
        return [f'c{node_id}', 0 if kind == 'VAEEncodeAdvanced' else slot]

    def export(node_id):
        key = f'c{node_id}'
        if key in graph:
            return
        if node_id in visiting:
            raise ValueError(f'Cyclic template connection: {node_id}')
        visiting.add(node_id)
        node = nodes[node_id]
        kind = node['type']
        inputs = {}
        values = iter(node.get('widgets_values') or [])
        for item in node.get('inputs', []):
            if not item.get('widget'):
                continue
            value = next(values)
            inputs[item['name']] = value
            if item['name'] in ('seed', 'noise_seed'):
                control = next(values)
                if control not in ('fixed', 'randomize', 'increment', 'decrement'):
                    raise ValueError(f'Unexpected seed control: {node_id}')
        # These core nodes store their widgets without converted input sockets.
        if kind == 'CLIPTextEncode':
            inputs['text'] = node['widgets_values'][0]
        elif kind == 'LoadImage':
            inputs['image'] = node['widgets_values'][0]
        elif kind == 'SaveImage':
            inputs['filename_prefix'] = '$name'
        for item in node.get('inputs', []):
            if item.get('link') is not None:
                inputs[item['name']] = source(node, item['name'])
        if kind == 'VAEEncodeAdvanced':
            if any(item.get('link') for item in node['inputs'] if item['name'] in ('image_1', 'image_2', 'mask', 'latent')):
                raise ValueError('Only the original empty 16-channel latent branch is supported here.')
            kind = 'EmptySD3LatentImage'
            inputs = dict(width=inputs['width'], height=inputs['height'], batch_size=1)
        elif kind == 'GetImageSize+':
            kind = 'GetImageSize'
            inputs = dict(image=source(node))
        elif kind == 'ClipLoaderGGUF':
            kind = 'CLIPLoaderGGUF'
            inputs.pop('device', None)
        inputs.update(replacements.get(node_id, {}))
        # Attention acceleration is optional; PyTorch SDPA is the installed core
        # backend. It does not change the template's sampler or conditioning.
        if kind == 'UltimateSDUpscale':
            inputs['tiled_decode'] = True
            inputs['batch_size'] = 1
        if kind == 'FaceDetailer':
            inputs['tiled_encode'] = True
            inputs['tiled_decode'] = True
        graph[key] = dict(class_type=kind, inputs=inputs)
        visiting.remove(node_id)

    export(output)
    graph['8'] = graph.pop(f'c{output}')
    return graph


def main():
    hades = read_graph('chromaHDSimpleWorkflowMulti_v30.zip')
    full = read_graph('comfyuiChroma1HdFull_v10.zip')
    hades_graph = compile_graph(hades, 174, {}, {
        9: dict(text='$prompt'), 169: dict(model_name='4xNomosWebPhoto_RealPLKSR.safetensors'),
    })
    hades_graph['c102'] = dict(class_type='UNETLoader', inputs=dict(
        unet_name='velvetChroma_v20FP16.safetensors', weight_dtype='default'))
    full_replacements = {node['id']: dict(text='$prompt') for node in full['nodes']
                         if node['id'] in (157, 90, 108, 184)}
    for node in full['nodes']:
        if node['type'] == 'UNETLoader':
            full_replacements[node['id']] = dict(unet_name='Chroma1-HD-fp8_scaled_defaultloader_hybrid_large_rev2.safetensors')
        elif node['type'] == 'CLIPLoader':
            full_replacements[node['id']] = dict(clip_name='t5xxl_fp8_e4m3fn_scaled.safetensors')
        elif node['type'] == 'ControlNetLoader':
            full_replacements[node['id']] = dict(control_net_name='chroma_union_pro_2.safetensors')
    full_replacements[176] = dict(image='$pose')
    full_replacements[258] = dict(image='$color')
    # Replace the author's manual disk handoffs with direct image connections.
    # The five stages preserve their original sampling, ControlNet, colour,
    # curve and upscaling settings. The interactive mask/batch-editor branches
    # are separate tools in the source graph, not part of this pipeline.
    full_graph = compile_graph(full, 137, {
        100: (268, 0), 118: (211, 0), 193: (220, 0), 140: (228, 0),
    }, full_replacements)
    for graph in (hades_graph, full_graph):
        for node in graph.values():
            for name in ('seed', 'noise_seed'):
                if name in node['inputs']:
                    node['inputs'][name] = '$seed'
        for node in graph.values():
            for value in node['inputs'].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    if value[0] not in graph:
                        raise ValueError(f'Unresolved graph reference: {value}')
    DESTINATION.write_text(json.dumps(dict(chroma_hades=hades_graph, chroma_full=full_graph), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Compiled HaDeS {len(hades_graph)} nodes; Full {len(full_graph)} nodes.')


if __name__ == '__main__':
    main()
