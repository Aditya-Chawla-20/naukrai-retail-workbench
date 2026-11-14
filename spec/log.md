# Implementation and verification log

| Step | Decision and observed result |
|---|---|
| Read the five-page assessment | Identified four mandatory areas and chose AI Engineering. See [requirements](requirements.md). |
| Research | Reviewed public submissions and licensed upstream projects. Reproduced a misleading pass in a public sample where a count question computed revenue, and a twofold join fan-out. Used these as regression targets. |
| Build the data path | Created streaming CSV validation, before/after profiling, deterministic transformation plan, preserved artifacts, stable IDs and versioned publication. |
| Implement retail analytics | Defined one audited order-line → catalog left join and metrics for sales, order value and returns. Verified 3 returned out of 5 sold in the West Apparel group. |
| Integrate chat and UI | Added typed plans, execution bounds, persisted versioned context, result previews and a native browser workspace. |
| Qualify NVIDIA | Account catalog returned 200. Two Nemotron endpoints returned account-entitlement 404. Nemotron 3.5 Lightning worked. Added fenced JSON handling and deterministic scope commands after observing an incorrectly widened West answer. |
| Record walkthrough | Captured the real running app with synthetic data and local narration. The 3:37 MP4 shows cleaning, an ambiguous question, a retail join and two turns, and malformed-file recovery. |
| Final audit | See [eval instructions and saved outputs](evals.md). |
| Fill eval coverage gaps | Added exact assertion cases for filtering, sort/limit, distinct, comparison, bottom ranking, descriptive stats, raw-data refusal and unknown field rejection. Exercised orphan counts and all-null columns. |
| Protect batch publication | Used a unique temporary file and atomic replace for evaluator output. Clarification now takes precedence over ambiguous fallback dataset selection; unsupported questions do not become scope commands. |
| Clean-clone rerun and output archive | Ran ten tests, two independent key-free batch runs, byte-compared published artifacts and decoded the walkthrough. Saved complete sanitized evidence under `spec/evals/`. |
| Live final smoke | Recorded exact West and Completed answers, targeted clarification, persisted history and separate-workspace denial. Saved planner, plan and trace with no credentials. |
| Assemble submission | Built the browser-readable submission report, linked the complete outputs and embedded the verified walkthrough. Checked keyboard interaction, file links and video metadata at 320, 390, 768 and 1440 pixels. |
| Handoff scope | The owner chose a public GitHub repository. The hiring-channel destination will be supplied later. The original assessment PDF stays in the local workspace. |
| Public GitHub verification | Published the repository and cloned anonymously at `caf1c14`. The key-free evaluator reproduced all four case results and every archived CSV/report byte. |
| Walkthrough narration revision | Replaced narration with the Andrew male neural voice, fitted the narration to each scene and decoded the replacement. The original video stream hash matched. |
