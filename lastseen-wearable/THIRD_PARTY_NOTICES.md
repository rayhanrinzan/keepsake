# Third-party notices

Last Seen uses the open-source projects below as dependencies (installed with `pip`, not vendored). No source code from them is copied into this repository. Each is used under its own license; follow the link for the full text.

| Project | License | What we use it for |
|---|---|---|
| [Ultralytics](https://github.com/ultralytics/ultralytics) | [AGPL-3.0](https://github.com/ultralytics/ultralytics/blob/main/LICENSE) | YOLO-World open-vocabulary detector and the YOLO person detector with ByteTrack (`lastseen/vision/detector.py`, `lastseen/vision/people.py`) |
| [OpenAI CLIP](https://github.com/openai/CLIP) | [MIT](https://github.com/openai/CLIP/blob/main/LICENSE) | ViT-B/32 image and text embeddings that tell our items apart (`lastseen/vision/embedder.py`) |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | [Apache-2.0](https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE) | Hand landmarks for touch, pick-up and put-down (`lastseen/vision/hands.py`) |
| [Roboflow Supervision](https://github.com/roboflow/supervision) | [MIT](https://github.com/roboflow/supervision/blob/develop/LICENSE.md) | `Detections` utilities for the person tracker output (`lastseen/vision/people.py`) |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | [MIT](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE) | Local speech-to-text for spoken questions (`lastseen/voice/listen.py`) |
| [FastAPI](https://github.com/fastapi/fastapi) | [MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE) | Web server: dashboard, memory frame, stream, WebSocket, REST (`lastseen/server/app.py`) |
| [OpenCV](https://github.com/opencv/opencv) | [Apache-2.0](https://github.com/opencv/opencv/blob/4.x/LICENSE) | Camera capture, image processing, snapshots and clips |
| [PyObjC](https://github.com/ronaldoussoren/pyobjc) | [MIT](https://github.com/ronaldoussoren/pyobjc/blob/master/License.txt) | Finding the iPhone (Continuity Camera) by name via AVFoundation (`lastseen/capture/devices.py`) |

**AGPL-3.0 note:** because Ultralytics is AGPL-3.0, this repository must stay public and open source.

Model weights downloaded at runtime (YOLO-World, YOLO person model, CLIP ViT-B/32, MediaPipe hand landmarker, Whisper) are covered by their publishers' licenses.

## Inspiration and references (no code used)

- **reCall** ([github.com/darryltanzil/reCall](https://github.com/darryltanzil/reCall)), a Hack the North project: inspiration for the idea of a camera that remembers where things are. The repo has no license, so none of its code is used. Our approach is different: local object-level event tracking instead of cloud frame captioning.
- **Visiona** ([github.com/paavansirivardhan123/Visiona](https://github.com/paavansirivardhan123/Visiona), MIT): read as a reference for its object-memory, embedding re-identification and push-to-talk ideas. No code was copied from it; our identity and voice code was written for this project (ported from our own prototype in `legacy/`).
