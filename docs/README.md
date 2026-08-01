# Beagle documentation

Beagle is a code reviewer. It reads a diff and it writes findings. One server gives service to one repository.

These documents use ASD-STE100 Simplified Technical English. The sentences are short. Each term has one meaning. The documents use the active voice.

## Documents

| Document | Content |
| --- | --- |
| [architecture.md](architecture.md) | The parts, the folders, and the flows |
| [install.md](install.md) | How to install the server and how to start it |
| [configuration.md](configuration.md) | Each configuration key and its default value |
| [reviews.md](reviews.md) | How a review operates, and how to ask for one |
| [memory.md](memory.md) | How Beagle learns from the feedback of the team |
| [github.md](github.md) | Pull request reviews and comment commands |
| [api.md](api.md) | The HTTP interface |
| [cli.md](cli.md) | The commands |
| [operations.md](operations.md) | Data, costs, failures, and repairs |
| [prompts.md](prompts.md) | How to change the instructions that Beagle gives to the models |

## What Beagle does

1. Beagle keeps a copy of the repository. The copy is a bare clone.
2. Beagle makes an index of the code. The index holds the symbols, the call graph, and the text of each block of code.
3. When you ask for a review, Beagle reads the diff. Beagle then collects the related code from the index.
4. Beagle sends the diff and the related code to a model. The model returns findings.
5. Beagle removes the findings that the team dismissed before. Beagle then checks the most important findings a second time.
6. Beagle writes a summary and keeps the result.

## Severity levels

Beagle gives one level to each finding.

| Level | Meaning |
| --- | --- |
| P0 | Do not merge. The code has a defect that causes damage or exposure. |
| P1 | Correct this before you merge. The code has a probable defect. |
| P2 | Correct this soon. The problem is real but it does not cause damage now. |
| P3 | Correct this when you can. The author decides when. |
| P4 | A small improvement. |
| P5 | A very small improvement. Beagle reports these rarely. |

A security finding in application code is always P0. The pipeline sets this level. The model cannot make the level lower. Refer to [reviews.md](reviews.md) for the rules.

## Design limits

- One server gives service to one repository.
- One index exists for each repository. Beagle does not make an index for each pull request.
- Beagle keeps the configuration in one file. There are no environment variables and there are no command options for configuration.
- Three SQLite files hold the data. Refer to [operations.md](operations.md).
- The code applies the important limits, not the prompts. A person who changes a prompt cannot remove them. Refer to [prompts.md](prompts.md).
- The GitHub interface is optional. Without a token, everything else operates.
