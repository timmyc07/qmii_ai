"""Chroma1-HD graph using ComfyUI core nodes and the author's T2I recipe."""
MODEL = 'Chroma1-HD-fp8_scaled_defaultloader_hybrid_large_rev2.safetensors'
ENCODER = 't5xxl_fp8_e4m3fn_scaled.safetensors'
VAE = 'ae.safetensors'


def build_workflow(prompt, seed, name):
    def node(kind, **inputs):
        return dict(class_type=kind, inputs=inputs)

    return {
        '1': node('UNETLoader', unet_name=MODEL, weight_dtype='default'),
        '2': node('CLIPLoader', clip_name=ENCODER, type='chroma', device='default'),
        '3': node('VAELoader', vae_name=VAE),
        '4': node('T5TokenizerOptions', clip=['2', 0], min_padding=1, min_length=0),
        '5': node('CLIPTextEncode', clip=['4', 0], text=prompt),
        '6': node('CLIPTextEncode', clip=['4', 0], text='low quality, blurry, deformed, unfinished'),
        '7': node('EmptySD3LatentImage', width=1024, height=1024, batch_size=1),
        '8': node('SaveImage', images=['15', 0], filename_prefix=name),
        '9': node('ModelSamplingAuraFlow', model=['1', 0], shift=1.0),
        '10': node('CFGGuider', model=['9', 0], positive=['5', 0], negative=['6', 0], cfg=3.8),
        '11': node('RandomNoise', noise_seed=seed),
        '12': node('KSamplerSelect', sampler_name='euler'),
        '13': node('BetaSamplingScheduler', model=['9', 0], steps=26, alpha=0.45, beta=0.45),
        '14': node('SamplerCustomAdvanced', noise=['11', 0], guider=['10', 0], sampler=['12', 0],
                   sigmas=['13', 0], latent_image=['7', 0]),
        '15': node('VAEDecode', samples=['14', 0], vae=['3', 0]),
    }


def validate_models(root):
    for folder, filename in [('diffusion_models', MODEL), ('text_encoders', ENCODER), ('vae', VAE)]:
        path = root / folder / filename
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError(f'Chroma1-HD 模型未安裝完整，請執行 tools/install-chroma.ps1：{filename}')
