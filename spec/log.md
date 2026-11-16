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
| Aditya New Qwen narration attempt | The single 2,978-character render reached low memory, so it was canceled before a storage failure. After freeing internal space, the owner asked for smaller passages. |
| Generate narration in bounded passages | Generated all seven transcript paragraphs with Voicebox profile Aditya New and Qwen3-TTS 1.7B. Clip durations: 23.60, 27.76, 17.52, 34.24, 25.12, 20.08 and 29.52 seconds (177.84 seconds total). Each passage completed; memory pressure recovered between clips. Source WAVs and assembled narration are on the external SSD. |
| Rebuild the walkthrough | Matched the seven voice clips to the original narration's long scene pauses, then muxed AAC audio with the original H.264 video stream. The final MP4 is 216.628 seconds; the video stream SHA-256 is unchanged and FFmpeg decoded the file end to end. Preserved the previous Andrew-narrated MP4 on the external SSD. |
| Fix cloned-voice artifact and pacing | Whisper confirmed all seven source WAVs begin with an unrequested “Courage,” matching the final word in the Aditya New voice-reference transcript. Trimmed 8 frames (0.67 seconds) from each clip, paired each with its original screen-capture section in an editable Remotion sequence, and stopped time-stretching the voice. Added 1.25-second section pauses to keep the assignment's 3-minute minimum. The 180.437-second MP4 decoded end to end; a Whisper pass on its final audio found the intended script at each section start and no repeated “courage.” `npm run lint` passed. |
