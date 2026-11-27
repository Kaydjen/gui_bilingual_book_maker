**Disclaimer:**
This is only my brief retelling and interpretation of the information I learned from this study. I do not guarantee a complete picture and I did not read the study in full; I only went through the information I needed: the details of the experiments, the data, and the conclusions drawn from them. I picked out what seemed to me the most significant and wrote the short summary that you can read below.

That is, I am not responsible for the completeness, level of detail or accuracy of the information. If you want to go through everything in more detail, please refer to the authors' original paper.

The text was formatted by a LLM; the numbers were checked against the paper.


# Paper card

All facts below are taken from the paper itself; the link after each fact points to the page of the PDF.

- **Authors:** Marzena Karpinska and Mohit Iyyer, University of Massachusetts Amherst. [p. 419](https://aclanthology.org/2023.wmt-1.41.pdf#page=1)
- **Year and venue:** 2023, Proceedings of the Eighth Conference on Machine Translation (WMT), pages 419-451, December 6-7, 2023. [p. 419](https://aclanthology.org/2023.wmt-1.41.pdf#page=1)
- **Models used:**
  - GPT-3.5, the `text-davinci-003` checkpoint (instruction-tuned with human feedback), used through few-shot prompting. [p. 422](https://aclanthology.org/2023.wmt-1.41.pdf#page=4)
  - The annotations were completed on translations from a `text-davinci-003` checkpoint obtained before the API release of ChatGPT and GPT-4. [p. 419, footnote 2](https://aclanthology.org/2023.wmt-1.41.pdf#page=1)
  - Google Translate (GTR) as a baseline; all paragraphs were translated in January 2023 through the Google Translate API. [p. 423, footnote 14](https://aclanthology.org/2023.wmt-1.41.pdf#page=5)
  - GPT-4 only in a preliminary analysis in the appendix. [p. 444](https://aclanthology.org/2023.wmt-1.41.pdf#page=26)
- **Language pairs:** 18 pairs. Source languages: English, Polish, Russian, Czech, French, German, Japanese, Chinese. Target languages: English, Japanese, Polish only (so Russian is a source language only, never a target). [p. 422](https://aclanthology.org/2023.wmt-1.41.pdf#page=4). The full list of 18 pairs is in Figure 1: [p. 419](https://aclanthology.org/2023.wmt-1.41.pdf#page=1)
- **Data size:**
  - 20 paragraphs from each of 18 recently published translated novels, giving 360 aligned source-target paragraphs; each paragraph has at least two sentences, mean 7.45 sentences (std 4.14). [p. 421-422](https://aclanthology.org/2023.wmt-1.41.pdf#page=3)
  - Human evaluation on 10 paragraphs per language pair, so 180 source paragraphs, each with three comparisons (PARA vs SENT, PARA vs PARA_SENT, PARA vs GTR); that is 180 judgments per comparison. [p. 424](https://aclanthology.org/2023.wmt-1.41.pdf#page=6)
  - The introduction states annotations on 720 pairs of translated paragraphs. [p. 420](https://aclanthology.org/2023.wmt-1.41.pdf#page=2)
  - Annotators: 13 translators recruited (12 via Upwork, one hired directly); about 350 hours of effort for annotation and analysis; total cost $955. [p. 423-424](https://aclanthology.org/2023.wmt-1.41.pdf#page=5), [p. 419](https://aclanthology.org/2023.wmt-1.41.pdf#page=1)


**My conclusion:**
Translation of the whole paragraph was chosen more often. One of the important arguments in favor of PARA is that the model can translate a paragraph by merging or splitting the source sentences (this often happens in real human translation too: by the authors' estimate, at least 55% of the target paragraphs in their dataset contained a merge or split of source sentences. Put simply: one original sentence does not always give exactly one translated sentence.). So I think the text should not be split into pieces smaller than paragraphs. The model should see a complete semantic unit.

[Source: p. 420](https://aclanthology.org/2023.wmt-1.41.pdf#page=2).

# Summary of the study:

Compared:
1. `SENT vs PARA` - translating individual sentences against translating the whole paragraph.
2. `PARA_SENT vs PARA` - translating sentences with the context provided against translating the whole paragraph.
3. `GTR vs PARA` - Google Translate against translating the whole paragraph.
    

## Main results

For each comparison, 180 pairs of translations were evaluated: 10 paragraphs for each of the 18 language pairs.

[Source: section 4, p. 424-425](https://aclanthology.org/2023.wmt-1.41.pdf#page=6). Note the tables on page 425 - they are quite illustrative.

|Comparison|Chose the first method|Chose PARA|
|---|---|---|
|SENT vs PARA|51 (28.33%)|**129 (71.67%)**|
|PARA_SENT vs PARA|60 (33.33%)|**120 (66.67%)**|
|GTR vs PARA|30 (16.67%)|**150 (83.33%)**|

Note: these numbers are from the published WMT 2023 version ([p. 425](https://aclanthology.org/2023.wmt-1.41.pdf#page=7)). The earlier arXiv preprint ([2304.03245](https://arxiv.org/abs/2304.03245)) reports slightly different figures for SENT vs PARA: 71.1% (78.5% excluding "unsure").

How to read these results:
- **SENT vs PARA:** out of 180 judgments, in 129 cases the translation of the whole paragraph turned out better than the isolated translation of sentences.
- **PARA_SENT vs PARA:** even when PARA_SENT received the whole source paragraph as context, the translation of the whole paragraph still won in 120 cases.
- **GTR vs PARA:** Google Translate lost in 150 cases out of 180.

This is not a percentage of correct translations. It is the share of human preferences when comparing two variants.

## How confident were the translators?

There is one more characteristic here - `Confidence`.

After choosing the better translation, the translator indicated how significant the advantage of the chosen variant was.

- `Confident` - the chosen translation is significantly better.
- `Unsure` - the choice was difficult because both translations were of roughly the same quality.

Here are the actual counts:

|Comparison|Chosen method|Confident|Unsure|
|---|---|---|---|
|SENT vs PARA|SENT|22|29|
||PARA|85|44|
|PARA_SENT vs PARA|PARA_SENT|28|32|
||PARA|59|61|
|GTR vs PARA|GTR|15|15|
||PARA|118|32|

[Source: Figure 5, p. 425](https://aclanthology.org/2023.wmt-1.41.pdf#page=7). The link is the same as above, the same tables. 

## An example of how it all looked

**Note:** below is a made-up example for illustration, not a fragment from the experiment. In the study the target languages were English, Japanese and Polish. Russian was used as one of the source languages.

**Source paragraph:**

```
Anna opened the door. Mark was waiting outside. She let him in.
```

For illustration, let us assume that the context sentences contain an ambiguity that the model has to resolve.

## Comparison of the inputs

|Element|SENT|PARA_SENT|PARA|
|---|---|---|---|
|5 demonstrations|Sentences|Paragraphs + marked sentences|Paragraphs|
|Whole original|No|Yes|Yes|
|Previous translation of the current paragraph|No|Yes|No|
|Marked sentence|No|Yes|No|
|What is generated|One sentence|One sentence|Whole paragraph|

The authors manually prepared five demonstrations for each language pair - 90 in total. For `SENT` these were pairs of individual sentences and their translations; for `PARA_SENT` - paragraphs with a marked sentence and a partial translation; for `PARA` - whole paragraphs with translations.

Because of the context window limit, in about 10% of requests `PARA` and `PARA_SENT` used four or fewer demonstrations.

[Source: section 3.2, p. 422](https://aclanthology.org/2023.wmt-1.41.pdf#page=4) and [Table 1, p. 423](https://aclanthology.org/2023.wmt-1.41.pdf#page=5).

The authors' repository also contains the demonstration data itself: [SENT examples](https://github.com/marzenakrp/LiteraryTranslation/blob/main/base_data/prompt_demonstrations_sent.tsv) and [PARA examples](https://github.com/marzenakrp/LiteraryTranslation/blob/main/base_data/prompt_demostrations_para.tsv).

Below are schematic examples of the request structure, not the authors' verbatim prompts. Real examples can be seen in appendix C of the paper: [SENT - Figure 8](https://aclanthology.org/2023.wmt-1.41.pdf#page=17), [PARA_SENT - Figure 9](https://aclanthology.org/2023.wmt-1.41.pdf#page=18), [PARA - Figure 10](https://aclanthology.org/2023.wmt-1.41.pdf#page=19).

### 1. SENT - translation without context

The model receives only one sentence.

**Input:**

```
Original text in English:
Anna opened the door.

Translation into Russian:

  
// + 5 examples like:

//Original text in English:
//The old man looked at the window.

//Translation into Russian:
//Старик посмотрел в окно.


//Original text in English:
//It was already getting dark.

//Translation into Russian:
//Уже начинало темнеть.


//[Example 3]


//[Example 4]


//[Example 5]
```

**Output:**

```
Анна открыла дверь.
```

### 2. PARA_SENT - translating a sentence with context

The model receives the whole source paragraph, but has to translate only one marked sentence.

Suppose we have reached the third sentence.

**Input:**

```
5 examples

Original text in English:
Anna opened the door.
Mark was waiting outside.
<translate>She let him in.</translate>

Translation into Russian:
Анна открыла дверь.
Марк ждал снаружи.
<translated>
```

**Output (continuation of the input request):**

```
Она впустила его.</translated>
```

So the model sees the whole source paragraph and the already translated part of the target paragraph. The `<translated>` tag at the end of the input text shows where the translation of the marked sentence should begin.

### 3. PARA - translating the whole paragraph

Here the model receives the whole source paragraph and has to translate it in full.

**Input:**

```
5 examples

Original text in English:
Anna opened the door.
Mark was waiting outside.
She let him in.

Translation into Russian:
```

**Output:**

```
Анна открыла дверь.
Марк ждал снаружи.
Она впустила его.
```

#### 4. GTR - Google Translate

Everything is simpler here: the authors used the Google Translate API. It was also given whole paragraphs.

There is one caveat: the authors assume that Google Translate may have split the paragraphs into separate sentences on its own and translated them one by one.

[Source: footnote 14, p. 423](https://aclanthology.org/2023.wmt-1.41.pdf#page=5).

**Input:**

```
Anna opened the door.
Mark was waiting outside.
She let him in.
```

**Output:**

```
Анна открыла дверь.
Марк ждал снаружи.
Она впустила его.
```

---

# Limitations (what this paper does not tell us)

- **An older model, and not ours.** All main results are for GPT-3.5 `text-davinci-003`, with annotations done before the ChatGPT and GPT-4 APIs were released ([p. 419, footnote 2](https://aclanthology.org/2023.wmt-1.41.pdf#page=1)). GPT-4 is covered only by a preliminary look; the authors write that no broader conclusions should be made without further testing, and that it "does not magically solve all of these issues" ([p. 444](https://aclanthology.org/2023.wmt-1.41.pdf#page=26)). Gemini is not tested.
- **Few-shot prompting, one paragraph at a time.** Each prompt has five hand-curated demonstrations per language pair, taken from other novels, and the model gets a single paragraph (mean 7.45 sentences). About 10% of the PARA and PARA_SENT data was translated with four or fewer demonstrations because of the context-size limit ([p. 422](https://aclanthology.org/2023.wmt-1.41.pdf#page=4)). Context from neighbouring paragraphs is not part of the experiments; integrating paragraphs into chapters is left for future work ([p. 427](https://aclanthology.org/2023.wmt-1.41.pdf#page=9)). The only mention is one example in a footnote, where adding three preceding paragraphs gave accurate translations from both GPT-3.5 and GPT-4 ([p. 444, footnote 41](https://aclanthology.org/2023.wmt-1.41.pdf#page=26)).
- **A small, pairwise human evaluation.** Only 10 paragraphs per language pair were annotated, 180 per comparison, by 13 translators ([p. 424](https://aclanthology.org/2023.wmt-1.41.pdf#page=6)); Table 10 lists one translator profile per language pair, and three pairs were annotated by the first author ([p. 439](https://aclanthology.org/2023.wmt-1.41.pdf#page=21)). The result is a choice between two translations, not an absolute quality score; all 360 paragraphs were also used for automatic metrics, which the authors do not consider reliable for document-level and literary text ([p. 423-424](https://aclanthology.org/2023.wmt-1.41.pdf#page=5)).
- **Critical errors persist (the title).** Across all annotated paragraphs, PARA still has 483 mistranslations and 105 grammar errors (SENT: 633 and 156) ([Table 2, p. 426](https://aclanthology.org/2023.wmt-1.41.pdf#page=8)). The translators' reports of significant content omissions or additions were a binary yes/no flag only; PARA has the most reported omissions: 37, against 17 for SENT, 32 for PARA_SENT and 22 for GTR ([Table 12, p. 444](https://aclanthology.org/2023.wmt-1.41.pdf#page=26); [p. 424, footnote 22](https://aclanthology.org/2023.wmt-1.41.pdf#page=6)). The authors also note that PARA sometimes merges two sentences with different subjects and attributes everything to one of them ([p. 443](https://aclanthology.org/2023.wmt-1.41.pdf#page=25)).
- **Languages.** Target languages are only English, Japanese and Polish; Russian appears only as a source language, and all languages are mid- or high-resource ([p. 422](https://aclanthology.org/2023.wmt-1.41.pdf#page=4); [p. 428](https://aclanthology.org/2023.wmt-1.41.pdf#page=10)). English to Russian was not evaluated.
- **Text type.** The data are 360 paragraphs from 18 novels whose translations were mostly published after 2021 (to limit data contamination) ([p. 421](https://aclanthology.org/2023.wmt-1.41.pdf#page=3)); the authors say that a full-length novel extends far beyond paragraph-level translation ([p. 427](https://aclanthology.org/2023.wmt-1.41.pdf#page=9)).

# What it means for us

- (inference) The paper supports keeping the paragraph as the minimal unit: for GPT-3.5 the whole-paragraph translation beat sentence-by-sentence translation in 18 language pairs. Our "one paragraph = one block" matches this, but the result was measured on an older model and not on EN->RU, so it is a reason for the design, not proof that it works with Gemini.
- (inference) Our request carries the 3 previous paragraphs (source and translation) as context. The paper did not test this setup; its only related evidence is one anecdotal example in a footnote. We should treat the benefit as a plausible hypothesis and check it on our own samples.
- (inference) Requests with 5 or 10 blocks are also outside what the paper measured (one paragraph per request). Since content omissions were the error type where PARA did worst, it is worth checking that every block in the answer is present and not shortened or merged with its neighbour.
- (inference) The title's warning matters for fiction: even the best method in the paper makes many mistranslations and omissions, so a human look at sample output (omissions, names, pronouns and consistency) stays necessary.

---

# Sources

## Links

1. Karpinska, M., & Iyyer, M. (2023). _Large Language Models Effectively Leverage Document-level Context for Literary Translation, but Critical Errors Persist._ Proceedings of the Eighth Conference on Machine Translation (WMT 2023), 419–451. [Open the published paper](https://aclanthology.org/2023.wmt-1.41/) · [PDF](https://aclanthology.org/2023.wmt-1.41.pdf) · [DOI](https://doi.org/10.18653/v1/2023.wmt-1.41)
    
2. Karpinska, M., & Iyyer, M. (2023). _Large Language Models Effectively Leverage Document-level Context for Literary Translation, but Critical Errors Persist._ arXiv:2304.03245. [https://arxiv.org/abs/2304.03245](https://arxiv.org/abs/2304.03245)
    
3. Karpinska, M., & Iyyer, M. (2023). _LiteraryTranslation — Experimental Dataset and Annotations._ GitHub Repository. [https://github.com/marzenakrp/LiteraryTranslation](https://github.com/marzenakrp/LiteraryTranslation)
