---
license: apache-2.0
size_categories:
- 1K<n<10K
---

# CyberMetric Dataset

<div align="center">
    <img width="800" alt="logo" src="https://cdn-uploads.huggingface.co/production/uploads/65ae586052e1b2aae48e01fb/BysIEXVZXZrOX6MJ7SBST.png">
</div>

# Description



The **CyberMetric Dataset** introduces a new benchmarking tool consisting of 10,000 questions designed to evaluate the cybersecurity knowledge of various Large Language Models (LLMs) within the cybersecurity domain. This dataset is created using different LLMs and has been verified by human experts in the cybersecurity field to ensure its relevance and accuracy. The dataset is compiled from various sources including standards, certifications, research papers, books, and other publications within the cybersecurity field.  We provide the dataset in four distinct sizes —small, medium, big and large— comprising 80, 500, 2000 and 10,000 questions, respectively.The smallest version is tailored for comparisons between different LLMs and humans. The CyberMetric-80 dataset has been subject to testing with 30 human participants, enabling an effective comparison between human and machine intelligence.

# Cite

The CyberMetric paper **"CyberMetric: A Benchmark Dataset based on Retrieval-Augmented Generation for Evaluating LLMs in Cybersecurity Knowledge"** has been accepted for publication in the 2024 IEEE International Conference on Cyber Security and Resilience (IEEE CSR 2024).

IEEE Xplore link: https://ieeexplore.ieee.org/document/10679494

Cite the paper:
```python
@INPROCEEDINGS{10679494,
  author={Tihanyi, Norbert and Ferrag, Mohamed Amine and Jain, Ridhi and Bisztray, Tamas and Debbah, Merouane},
  booktitle={2024 IEEE International Conference on Cyber Security and Resilience (CSR)}, 
  title={CyberMetric: A Benchmark Dataset based on Retrieval-Augmented Generation for Evaluating LLMs in Cybersecurity Knowledge}, 
  year={2024},
  volume={},
  number={},
  pages={296-302},
  keywords={Accuracy;Reverse engineering;Benchmark testing;NIST Standards;Risk management;Problem-solving;Computer security},
  doi={10.1109/CSR61664.2024.10679494}}
```
The paper is also available on arXiv: [https://arxiv.org/abs/2402.07688](https://arxiv.org/abs/2402.07688).

# Architecture

The CyberMetric dataset was created by applying different language models using Retrieval-Augmented Generation (RAG), with human validation included in the process. The AI-driven generation framework is illustrated in the following figure.

<div align="center">
  <img width="1102" alt="Framework" src="https://cdn-uploads.huggingface.co/production/uploads/65ae586052e1b2aae48e01fb/QM9RcAWBaEe0-OeN19nQL.png">
</div>


# Prompt 

Most of the evaluated models were instruction-fine-tuned, and the following prompts were used to obtain the correct answers in XML format.
```python
    def make_messages(question, answers):
        """
        Formats a single question+answers into a list of message dictionaries for the pipeline.
        """
        options_str = ', '.join([f"{key}) {value}" for key, value in answers.items()])
        instructions = (
            "You are a helpful AI assistant.\n"
            "Instructions:\n"
            "a. Carefully read the question.\n"
            "b. Choose the correct answer (A, B, C, or D) only.\n"
            "c. Do NOT include any explanation or additional text in the response.\n"
            "d. Always return the answer in this XML format: '<xml>answer</xml>'. "
            "For example, if the correct answer is D, then return <xml>D</xml>.\n\n"
        )
    
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": f"#Question: {question}\nOptions: {options_str}"}
        ]
        return messages

```
# LLM Leaderboard on CyberMetric Dataset

We have assessed and compared state-of-the-art LLM models using the CyberMetric dataset. The most recent evaluation was conducted on December 27th, 2024.




<div align="center">
    <img width="1065" alt="Cybermetric_result" src="https://cdn-uploads.huggingface.co/production/uploads/65ae586052e1b2aae48e01fb/uHKfs0GyJbXEBiXWqfkKF.png" />
</div>

