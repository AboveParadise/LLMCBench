import argparse
import os
import torch
from tqdm import tqdm
import numpy as np
import pandas as pd
from transformers import AutoTokenizer,AutoModelForCausalLM



def format_example(df, idx, include_answer=True):
    prompt = "premise:" + df.iloc[idx, 5]
    prompt += "\nhypothesis:" + df.iloc[idx, 6]
    
    prompt += "\nAnswer:"
    if include_answer:
        if df.iloc[idx, 0] == "entailment":
            prompt += " {}\n\n".format("A. yes")
        elif df.iloc[idx, 0] == "neutral":
            prompt += " {}\n\n".format("B. maybe")
        else:
            prompt += " {}\n\n".format("C. no")
    return prompt


def gen_prompt(train_df, k=-1):
    prompt = "Please identify whether the premise entails the hypothesis. The answer should be exactly 'A. yes', 'B. maybe' or 'C. no'\n\n"
    
    if k == -1:
        k = train_df.shape[0]
    for i in range(k):
        prompt += format_example(train_df, i)
    return prompt


@torch.no_grad()
def eval(args, model, tokenizer, dev_df, test_df):
    cors = []
    all_probs = []
    for i in tqdm(range(test_df.shape[0]), desc="Evaluating MNLI"):
        k = args.ntrain
        prompt_end = format_example(test_df, i, include_answer=False)
        train_prompt = gen_prompt(dev_df, k)
        prompt = train_prompt + prompt_end        
        input_ids = tokenizer(prompt, return_tensors="pt")["input_ids"].to("cuda")
        
        while input_ids.shape[-1] > args.seqlen:
            k -= 1
            train_prompt = gen_prompt(dev_df, k)
            prompt = train_prompt + prompt_end
            input_ids = tokenizer(prompt, return_tensors="pt")["input_ids"].to("cuda")
        
        label = test_df.iloc[i, 0]
        logits = model(input_ids=input_ids).logits[:,-1].flatten()
        probs = (
            torch.nn.functional.softmax(
                torch.tensor(
                    [
                        logits[tokenizer("A").input_ids[-1]],
                        logits[tokenizer("B").input_ids[-1]],
                        logits[tokenizer("C").input_ids[-1]],
                    ]
                ).float(),
                dim=0,
            )
            .detach()
            .cpu()
            .to(torch.float32)
            .numpy()
        )
        pred = {0: "entailment", 1: "neutral", 2: "contradiction"}[np.argmax(probs)]
        cor = pred == label
        cors.append(cor)
        all_probs.append(probs)

    acc = np.mean(cors)
    cors = np.array(cors)

    all_probs = np.array(all_probs)
    print("Average accuracy {:.4f}".format(acc))
    return cors, acc, all_probs


def main(args):
    # load your model and tokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.path, use_fast=False,add_bos_token=False,trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(args.path, device_map="auto",trust_remote_code=True)    
    train_df = pd.read_csv(os.path.join(args.data_dir, 'multinli_1.0_dev_matched.txt'), sep='\t', on_bad_lines="skip")[: args.ntrain]
    test_df = pd.read_csv(os.path.join(args.data_dir, "multinli_1.0_dev_mismatched.txt"), sep='\t', on_bad_lines="skip")
    cors, acc, probs = eval(args, model, tokenizer, train_df, test_df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ntrain", "-k", type=int, default=0, help='number of shots')
    parser.add_argument("--data_dir", "-d", type=str, default="data/MNLI", help='dataset location')
    parser.add_argument("--path", type=str, required=True, help='model checkpoint location')
    parser.add_argument("--seqlen", type=int, default=2048)
    args = parser.parse_args()
    main(args)