"""FLUX.1-dev checkpoint recipe using ComfyUI core nodes."""
MODEL = 'flux1-dev-fp8.safetensors'


def validate_models(root):
    path = root / 'checkpoints' / MODEL
    if not path.is_file() or not path.stat().st_size:
        raise ValueError('FLUX.1-dev 尚未安裝，請執行 tools/install-flux.ps1。')


def build_workflow(prompt, seed, name, lora=None, strength=1.0):
    def node(kind, **inputs):
        return dict(class_type=kind, inputs=inputs)

    graph = {
        '1': node('CheckpointLoaderSimple', ckpt_name=MODEL),
        '2': node('CLIPTextEncode', clip=['1', 1], text=prompt),
        '3': node('FluxGuidance', conditioning=['2', 0], guidance=3.5),
        '4': node('BasicGuider', model=['1', 0], conditioning=['3', 0]),
        '5': node('RandomNoise', noise_seed=seed),
        '6': node('KSamplerSelect', sampler_name='euler'),
        '7': node('BasicScheduler', model=['1', 0], scheduler='simple', steps=20, denoise=1.0),
        '13': node('EmptySD3LatentImage', width=1024, height=1024, batch_size=1),
        '9': node('SamplerCustomAdvanced', noise=['5', 0], guider=['4', 0], sampler=['6', 0],
                  sigmas=['7', 0], latent_image=['13', 0]),
        '10': node('VAEDecode', samples=['9', 0], vae=['1', 2]),
        '8': node('SaveImage', images=['10', 0], filename_prefix=name),
    }
    if lora:
        graph['12'] = node('LoraLoaderModelOnly', model=['1', 0], lora_name=lora, strength_model=strength)
        graph['4']['inputs']['model'] = ['12', 0]
        graph['7']['inputs']['model'] = ['12', 0]
    return graph
