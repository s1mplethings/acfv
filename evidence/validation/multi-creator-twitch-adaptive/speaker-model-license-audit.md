# Speaker and Lexical-Acoustic Model License Audit

Audit date: 2026-10-14. This is an engineering license inventory, not legal advice.
No new model weights were downloaded in this pass because the fixed TRAIN/VALIDATION/
HOLDOUT audio corpus is storage-blocked.

| Candidate | Code license | Weight/model-card license | Training-data note | Decision |
| --- | --- | --- | --- | --- |
| Current SpeechBrain ECAPA | Apache-2.0 in the already isolated dependency | Existing project dependency | VoxCeleb conditions remain independently relevant | Existing support-only baseline; benchmark not rerun |
| 3D-Speaker ERes2NetV2 | [3D-Speaker repository: Apache-2.0](https://github.com/modelscope/3D-Speaker/blob/main/LICENSE) | Not independently confirmed from an authoritative accessible model card | Upstream dataset terms must be checked per checkpoint | Do not download or run until the exact checkpoint license is confirmed |
| 3D-Speaker CAM++ | [3D-Speaker repository: Apache-2.0](https://github.com/modelscope/3D-Speaker/blob/main/LICENSE) | Not independently confirmed for the proposed 3D-Speaker checkpoint | Upstream dataset terms must be checked per checkpoint | Do not download or run |
| WeSpeaker ReDimNet2B6_LM | [WeSpeaker repository: Apache-2.0](https://github.com/wenet-e2e/wespeaker/blob/master/LICENSE) | [Official model card: Apache-2.0](https://huggingface.co/Wespeaker/wespeaker-voxceleb-redimnet2-B6-LM) | Listed by the [official pretrained-model inventory](https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md); VoxCeleb source conditions remain relevant | License metadata sufficient for a future isolated research benchmark |
| WeSpeaker CAM++ | [WeSpeaker repository: Apache-2.0](https://github.com/wenet-e2e/wespeaker/blob/master/LICENSE) | [Official model card: Apache-2.0](https://huggingface.co/Wespeaker/wespeaker-voxceleb-campplus) | VoxCeleb source conditions remain relevant | License metadata sufficient for a future isolated research benchmark |
| HuBERT base ls960 | Upstream implementation dependency-specific | [Official model card: Apache-2.0](https://huggingface.co/facebook/hubert-base-ls960) | LibriSpeech 960h is named by the model card | Eligible for a research lexical-acoustic POC once TRAIN trusted terms exist |
| WavLM base plus | Linked upstream repository license applies | [Official model card](https://huggingface.co/microsoft/wavlm-base-plus) links to [CC BY-SA 3.0](https://github.com/microsoft/UniSpeech/blob/main/LICENSE) | Model card lists several speech corpora | Research-only pending redistribution/commercial review |

The repository does not redistribute any of these weights. Speaker embeddings remain
WHO evidence; HuBERT/WavLM representations may only return WHAT candidates.
