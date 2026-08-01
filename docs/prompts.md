# Prompts

Beagle contains seven prompts. The prompts are in the package. You do not need to do anything to use them.

| Prompt | Model | Task |
| --- | --- | --- |
| `reviewer.md` | usual or strong | Read a unit and give findings |
| `plan.md` | small | Put the files into units and give risk tags |
| `dedup.md` | small | Put the same findings together and apply the limits |
| `verify.md` | strong | Examine a finding a second time |
| `summary.md` | small | Write the summary |
| `distill.md` | small | Make one block from the rules |
| `comment_classifier.md` | small | Put a pull request comment into one of four groups |
| `explain.md` | usual | Answer `@beagle explain` in a pull request thread |

The last two operate only with the GitHub interface. Refer to [github.md](github.md).

## How to change a prompt

1. Make a directory on the volume, for example `/data/prompts`.
2. Write the directory in the configuration:

   ```toml
   [prompts]
   dir = "/data/prompts"
   ```

3. Put a file in the directory. Use one of these two names:

   | Name | Result |
   | --- | --- |
   | `reviewer.md` | Your file replaces the prompt of Beagle |
   | `reviewer.append.md` | Beagle adds your file after the prompt of Beagle |

4. Start the server again.

Use `reviewer.append.md` if you can. Then you keep the prompt of Beagle and you add your own instructions. If you replace the prompt, you also replace the rules that make Beagle short and accurate.

## The parts that you must keep

If you replace `reviewer.md` or `verify.md`, your file must contain these two parts:

- `{{output_instructions}}`
- `{{severity_scale}}`

Beagle puts text in the place of each part. If a part is not there, the server stops when it starts. The server does not stop in the middle of a review.

These are the parts of each prompt:

| Prompt | Parts |
| --- | --- |
| `reviewer.md` | `{{severity_scale}}`, `{{repo_overview}}`, `{{instruction_files}}`, `{{conventions}}`, `{{output_instructions}}` |
| `plan.md` | `{{deep_paths}}`, `{{max_units}}`, `{{output_instructions}}` |
| `dedup.md` | `{{p5_cap}}`, `{{p4_cap}}`, `{{output_instructions}}` |
| `verify.md` | `{{severity_scale}}`, `{{output_instructions}}` |
| `summary.md` | `{{fail_on}}`, `{{output_instructions}}` |
| `distill.md` | `{{budget}}` |

## What a prompt cannot change

Some rules are in the code. A prompt cannot make them different:

- A security finding in application code is P0.
- One review has 12 findings at the most.
- One review has 2 P5 findings and 3 P4 findings at the most.
- The `min_severity` limit.

A person who writes a prompt cannot remove these controls by accident.

## How to see the prompts in use

```bash
beagle doctor
```

The command shows the name, the source, and an identifier for each prompt. The source shows `built-in`, `replaced by <path>`, or `built-in + append`.

The identifier changes when the text changes. Use it to see that your file is in use.

`GET /v1/schema` shows the same information. A different version of the prompts can explain a different result.

## The prompts and the cache

Beagle puts these items together at the start of each review request:

1. `reviewer.md`
2. The description of the repository
3. The instruction files of the repository
4. The rules of the team

These bytes do not change during a review. The model service keeps them in its cache, and the second call costs much less. Your prompt file is part of this group. A static file is good. Text that changes at each call is not.

## Before you change a prompt

Measure the change:

```bash
beagle eval
```

Write the numbers. Change the prompt. Run the command again and compare. A prompt that finds more problems can also make more noise. The numbers show both.
