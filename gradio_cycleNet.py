from share import *
import config

import cv2
import einops
import gradio as gr
import numpy as np
import torch
import random

from pytorch_lightning import seed_everything
from annotator.util import resize_image, HWC3
from annotator.canny import CannyDetector
from cycleNet.model import create_model, load_state_dict
from ldm.models.diffusion.ddim import DDIMSampler

model = create_model('./models/cycle_v21.yaml').cpu()
model.load_state_dict(load_state_dict('./models/cycle_sd21_ini.ckpt', location='cuda'))
model = model.cuda()
ddim_sampler = DDIMSampler(model)

def process(input_image, prompt, a_prompt, n_prompt, num_samples, image_resolution, ddim_steps, scale, seed, eta, source):
    with torch.no_grad():
        img = resize_image(HWC3(input_image), image_resolution)
        H, W, C = img.shape

        detected_map = HWC3(img)

        control = torch.from_numpy(detected_map.copy()).float().cuda() / 255.0
        control = torch.stack([control for _ in range(num_samples)], dim=0)
        control = einops.rearrange(control, 'b h w c -> b c h w').clone()

        if seed == -1:
            seed = random.randint(0, 65535)
        seed_everything(seed)

        if config.save_memory:
            model.low_vram_shift(is_diffusing=False)

        cond = {"c_concat": [control], "c_crossattn": [model.get_learned_conditioning([prompt+', '+a_prompt] * num_samples)], "uc_crossattn": [model.get_learned_conditioning([source] * num_samples)]}
        un_cond = {"c_concat": [control], "c_crossattn": [model.get_learned_conditioning([source+', '+n_prompt] * num_samples)], "uc_crossattn": [model.get_learned_conditioning([source] * num_samples)]}
        shape = (4, H // 8, W // 8)

        if config.save_memory:
            model.low_vram_shift(is_diffusing=True)

        samples, intermediates = ddim_sampler.sample(ddim_steps, num_samples,
                                                     shape, cond, verbose=False, eta=eta,
                                                     unconditional_guidance_scale=scale,
                                                     unconditional_conditioning=un_cond)

        if config.save_memory:
            model.low_vram_shift(is_diffusing=False)

        x_samples = model.decode_first_stage(samples)
        x_samples = (einops.rearrange(x_samples, 'b c h w -> b h w c') * 127.5 + 127.5).cpu().numpy().clip(0, 255).astype(np.uint8)

        results = [x_samples[i] for i in range(num_samples)]
    return results


block = gr.Blocks().queue()
with block:
    with gr.Row():
        gr.Markdown("## CycleNet")
    with gr.Row():
        with gr.Column():
            input_image = gr.Image(source='upload', type="numpy")
            source = gr.Textbox(label="source domain")
            prompt = gr.Textbox(label="target domain")
            run_button = gr.Button(label="Run")
            with gr.Accordion("Advanced options", open=False):
                num_samples = gr.Slider(label="Images", minimum=1, maximum=12, value=1, step=1)
                image_resolution = gr.Slider(label="Image Resolution", minimum=256, maximum=768, value=512, step=256)
                ddim_steps = gr.Slider(label="Steps", minimum=1, maximum=100, value=50, step=1)
                scale = gr.Slider(label="Guidance Scale", minimum=0.1, maximum=30.0, value=2.0, step=0.1)
                seed = gr.Slider(label="Seed", minimum=-1, maximum=2147483647, step=1, randomize=True)
                eta = gr.Number(label="eta (DDIM)", value=0.0)
                a_prompt = gr.Textbox(label="Added Prompt", value='best quality, extremely detailed')
                n_prompt = gr.Textbox(label="Negative Prompt",
                                      value='longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality')
        with gr.Column():
            result_gallery = gr.Gallery(label='Output', show_label=False, elem_id="gallery").style(grid=2, height='auto')
    ips = [input_image, prompt, a_prompt, n_prompt, num_samples, image_resolution, ddim_steps, scale, seed, eta, source]
    run_button.click(fn=process, inputs=ips, outputs=[result_gallery])

print(1)
block.launch(server_name='127.0.0.1')
