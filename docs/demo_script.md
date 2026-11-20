# Demo video: script and narration

**Video:** [`docs/demo/inspectbot_demo.mp4`](demo/inspectbot_demo.mp4). It is 4:29 long, 1920×1080 at 30 fps, with burned-in captions and no audio. Rebuild it with `scripts/make_demo_video.py` (see the bottom of this file).

The narration below is timed to each scene at a relaxed pace of about 2.3 words per second. Record it in one take over the video, or read it live while screen-sharing the app. Every scene can also be opened directly in the app through its URL, for example `http://localhost:8501/?run=S1&step=11`.

| # | Time | On screen | Narration |
| --- | --- | --- | --- |
| 1 | 0:00–0:06 | Title card | "This is InspectBot, a multi-agent research assistant for robotic visual inspection." |
| 2 | 0:06–0:18 | The problem | "One image often can't tell a crack from a shadow or a seam. A one-shot model guesses. InspectBot investigates, or says it can't know and hands the case to a human." |
| 3 | 0:18–0:32 | Architecture | "A CrewAI Flow coordinates three Claude agents: Planning, Inspection and Verification. Every robot action, procedure lookup and report goes through an MCP server, and the Coordinator enforces budgets and guardrails in code." |
| 4 | 0:32–0:42 | S1, first image (`?run=S1&step=5`) | "Scenario one: a metal bracket with a dark vertical line. Inspection records it as a hypothesis, crack, shadow or seam, not a verdict." |
| 5 | 0:42–0:53 | S1, Tree-of-Thought (`step=11`) | "Retrieval returns the bracket procedure. Tree-of-Thought compares three next steps. A lighting change scores highest, because a shadow moves and a crack doesn't." |
| 6 | 0:53–1:01 | S1, after the lighting change (`step=16`) | "One lighting change from the same camera pose, and the line is gone." |
| 7 | 1:01–1:12 | S1, report (`step=18`) | "No defect detected, for the inspected region only, citing both observations and procedure MB-1. The baseline, given the same image, called it a crack." |
| 8 | 1:12–1:23 | S3, reference fetched (`?run=S3&step=15`) | "Scenario three, a glass bottle. The seam procedure says to compare with the approved reference, so InspectBot fetches it without moving the robot at all." |
| 9 | 1:23–1:31 | S3, report | "The line is on the reference: it's the mold seam. The baseline again said crack." |
| 10 | 1:31–1:41 | S2, oblique view (`?run=S2&step=21`) | "Scenario two, a tile. The line stays put under two lights, and the low oblique view shows a raised edge." |
| 11 | 1:41–1:50 | S2, report | "That meets the crack criterion, so the report says suspected defect, with each condition backed by an observation." |
| 12 | 1:50–2:02 | S4, failed move (`?run=S4&step=13`) | "Scenario four: a clamp hides the target, and the one pose that can see past it is unreachable. The failure is logged and leaves no image, so it can never become evidence." |
| 13 | 2:02–2:11 | S4, Tree-of-Thought (`step=11`) | "Tree-of-Thought drops the lighting idea, because light can't see under a clamp." |
| 14 | 2:11–2:23 | S4, report and human review | "So the answer is insufficient evidence. The report names the uninspected region and the failed actions, and the reviewer's decision is recorded." |
| 15 | 2:23–2:36 | S5, retrieval (`?run=S5&step=9&open=rag`) | "Scenario five: there's no procedure for pump housings. A tile procedure matched best but is rejected by the category filter. InspectBot escalates in four seconds without moving the robot. The baseline guessed crack." |
| 16 | 2:36–2:46 | Evaluation table | "Across twenty scenarios, InspectBot was right twenty times; the baseline eight. Zero wrong definitive calls, versus twelve." |
| 17 | 2:46–2:56 | Evaluation targets | "Every target from the proposal is met, including zero false clears and full escalation of the cases that need a human." |
| 18 | 2:56–3:07 | MVTec AD, static image (`?run=M1`) | "Now real photos from the MVTec AD dataset. With one fixed camera nothing can move, so InspectBot compares the photo with an approved good reference, under a static-image procedure." |
| 19 | 3:07–3:17 | M1, report | "Every mark on this bottle rim also appears on the reference: no defect detected. The baseline flagged this good bottle as a defect." |
| 20 | 3:17–3:26 | M4, bottle under test (`?run=M4&step=9`) | "This bottle is labelled contaminated. Inspection notes a foreign shape at the rim and a dark spot in the bore, then fetches the reference." |
| 21 | 3:26–3:36 | M4, report | "Neither mark is on the reference, so the static criterion is met: suspected defect. The baseline called the rim continuous and cleared it." |
| 22 | 3:36–3:45 | M5, tile under test (`?run=M5&step=9`) | "This tile is labelled rough. Inspection finds a grainy, hazy patch in the top-right corner and asks for the reference." |
| 23 | 3:45–3:55 | M5, report | "The reference has no such patch, which matches the procedure's rough example: suspected defect. The baseline put it down to blur." |
| 24 | 3:55–4:06 | M3, report and human review (`?run=M3`) | "This tile has a few tiny flecks the reference lacks. They don't meet any defect criterion, but they don't match the reference either, so InspectBot asks a human instead of guessing." |
| 25 | 4:06–4:17 | MVTec evaluation (`?eval=mvtec-eval-20261120-1225`, Evaluation tab) | "On forty held-out images, precision is eighty-six percent against seventy-five, recall ninety-five against ninety, with half the false alarms on good parts. All three targets are met." |
| 26 | 4:17–4:29 | Closing card | "The trade-off is time: twenty-five to forty seconds per inspection. These are single pilot runs. Next steps are more MVTec categories and repeated runs. Thanks for watching." |

## Recording tips
- **Mac:** QuickTime → File → New Audio Recording. Play the video muted on a second screen and read along, then combine the two in iMovie or Clipchamp with the audio starting at 0:00.
- **Live demo instead:** run `streamlit run app/streamlit_app.py`, open the URLs in the table and drag the Step slider while you talk. Replay mode needs no API key and gives the same screens every time.

## Rebuilding the video
```bash
streamlit run app/streamlit_app.py --server.port 8599 &
pip install playwright
python scripts/make_demo_video.py --url http://localhost:8599
```

If no Chrome is installed, run `playwright install chromium` first. The script writes `docs/demo/inspectbot_demo.mp4`. Captions, durations and scenes are in the `SHOTS` list at the top of the script.
