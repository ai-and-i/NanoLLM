#!/usr/bin/env python3
import os
import sys
import time
import signal
import logging
import numpy as np

from termcolor import cprint

from nano_llm import NanoLLM, ChatHistory, ChatTemplates
from nano_llm.utils import ImageExtensions, ArgParser, KeyboardInterrupt, load_prompts, print_table 

# see utils/args.py for options
parser = ArgParser()

parser.add_argument("--prompt-color", type=str, default='blue', help="color to print user prompts (see https://github.com/termcolor/termcolor)")
parser.add_argument("--reply-color", type=str, default='green', help="color to print user prompts (see https://github.com/termcolor/termcolor)")

parser.add_argument("--disable-automatic-generation", action="store_false", dest="automatic_generation", help="wait for 'generate' command before bot output")
parser.add_argument("--disable-streaming", action="store_true", help="wait to output entire reply instead of token by token")
parser.add_argument("--disable-stats", action="store_true", help="suppress the printing of generation performance stats")

args = parser.parse_args()

prompts = load_prompts(args.prompt)
interrupt = KeyboardInterrupt()

# load model
model = NanoLLM.from_pretrained(
    args.model, 
    api=args.api,
    quantization=args.quantization, 
    max_context_len=args.max_context_len,
    vision_api=args.vision_api,
    vision_model=args.vision_model,
    vision_scaling=args.vision_scaling, 
)

# create the chat history
chat_history = ChatHistory(model, args.chat_template, args.system_prompt)


while True: 
    # get the next prompt from the list, or from the user interactivey
    if isinstance(prompts, list):
        if len(prompts) > 0:
            user_prompt = prompts.pop(0)
            cprint(f'>> PROMPT: {user_prompt}', args.prompt_color)
        else:
            break
    else:
        cprint('>> PROMPT: ', args.prompt_color, end='', flush=True)
        user_prompt = sys.stdin.readline().strip()
    
    print('')
    
    # special commands:  load prompts from file
    # 'reset' or 'clear' resets the chat history
    if user_prompt.lower().endswith(('.txt', '.json')):
        user_prompt = ' '.join(load_prompts(user_prompt))
    elif user_prompt.lower() == 'reset' or user_prompt.lower() == 'clear':
        logging.info("resetting chat history")
        chat_history.reset()
        continue

    # add the latest user prompt to the chat history
    if args.automatic_generation or user_prompt.lower() != 'generate':
        message = chat_history.append(role='user', msg=user_prompt)

    # images should be followed by text prompts
    if args.automatic_generation:
        if message.is_type('image'):
            logging.debug("image message, waiting for user prompt")
            continue
    elif user_prompt.lower() != 'generate':
        continue
        
    # get the latest embeddings (or tokens) from the chat
    embedding, position = chat_history.embed_chat(
        max_tokens=model.config.max_length - args.max_new_tokens,
        wrap_tokens=args.wrap_tokens,
    )

    # generate bot reply
    reply = model.generate(
        embedding, 
        streaming=not args.disable_streaming, 
        kv_cache=chat_history.kv_cache,
        stop_tokens=chat_history.template.stop,
        max_new_tokens=args.max_new_tokens,
        min_new_tokens=args.min_new_tokens,
        do_sample=args.do_sample,
        repetition_penalty=args.repetition_penalty,
        temperature=args.temperature,
        top_p=args.top_p,
    )
        
    # stream the output
    if args.disable_streaming:
        cprint(reply, args.reply_color)
    else:
        for token in reply:
            cprint(token, args.reply_color, end='', flush=True)
            if interrupt:
                reply.stop()
                interrupt.reset()
                break
            
    print('\n')
    
    if not args.disable_stats:
        print_table(model.stats)
        print('')
    
    # save the output and kv cache
    chat_history.append(role='bot', text=reply.text, tokens=reply.tokens)
    chat_history.kv_cache = reply.kv_cache
