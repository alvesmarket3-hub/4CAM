#!/usr/bin/env python3
"""
Viral Shorts Generator - Professional Version
2x2 Webcam Grid (equal size, no gaps) + Clean Game Area
"""

import os
import sys
import json
import uuid
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

_THIS_DIR = Path(__file__).parent
_PARENT   = _THIS_DIR.parent

def _find_base():
    if (_PARENT / "dist" / "index.html").exists():
        return _PARENT, _PARENT / "dist"
    if (_PARENT / "index.html").exists():
        return _PARENT, _PARENT
    if (_THIS_DIR / "dist" / "index.html").exists():
        return _THIS_DIR, _THIS_DIR / "dist"
    if (_THIS_DIR / "index.html").exists():
        return _THIS_DIR, _THIS_DIR
    (_PARENT / "dist").mkdir(exist_ok=True)
    return _PARENT, _PARENT / "dist"

BASE_DIR, STATIC_FOLDER = _find_base()
UPLOAD_FOLDER = BASE_DIR / "uploads"
OUTPUT_FOLDER = BASE_DIR / "outputs"
TEMP_FOLDER   = BASE_DIR / "temp"

for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, TEMP_FOLDER, STATIC_FOLDER]:
    folder.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(STATIC_FOLDER), static_url_path='')
CORS(app)

jobs = {}

@app.route('/')
def index():
    return send_file(STATIC_FOLDER / 'index.html')

@app.route('/<path:path>')
def static_files(path):
    file_path = STATIC_FOLDER / path
    if file_path.exists():
        return send_file(file_path)
    return send_file(STATIC_FOLDER / 'index.html')

@app.route('/api/health')
def health():
    ffmpeg_ok = shutil.which('ffmpeg') is not None
    ytdlp_ok = shutil.which('yt-dlp') is not None
    return jsonify({
        "status": "ok" if (ffmpeg_ok and ytdlp_ok) else "missing_deps",
        "ffmpeg_installed": ffmpeg_ok,
        "ytdlp_installed": ytdlp_ok,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/download', methods=['POST'])
def download_video():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({"error": "URL required"}), 400
    
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "downloading", "progress": 0, "message": "Başlatılıyor..."}
    
    def download_task():
        try:
            output_file = UPLOAD_FOLDER / f"{job_id}_video.mp4"
            
            # Windows dosya yolu sorunlarını çözmek için göreceli yol kullanıyoruz
            rel_output = os.path.relpath(output_file, BASE_DIR)
            
            cmd = [
                'yt-dlp',
                '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
                '--merge-output-format', 'mp4',
                '-o', rel_output,
                '--no-playlist',
                '--newline',
                '--no-warnings',
                '--hls-prefer-native',
                url
            ]
            
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                universal_newlines=True, cwd=str(BASE_DIR)
            )
            
            for line in process.stdout:
                if '[download]' in line and '%' in line:
                    try:
                        percent = line.split('%')[0].split()[-1]
                        jobs[job_id]["progress"] = int(float(percent))
                        jobs[job_id]["message"] = f"İndiriliyor... {int(float(percent))}%"
                    except:
                        pass
                elif '[Merger]' in line or 'Merging' in line:
                    jobs[job_id]["message"] = "Ses ve video birleştiriliyor..."
                    jobs[job_id]["progress"] = 95
            
            process.wait()
            
            if output_file.exists():
                info_cmd = ['ffprobe', '-v', 'error', '-show_entries', 
                           'format=duration,size', '-show_streams',
                           '-select_streams', 'v:0',
                           '-of', 'json', rel_output]
                info_result = subprocess.run(info_cmd, capture_output=True, text=True, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL)
                duration = 0
                width = 0
                height = 0
                try:
                    info = json.loads(info_result.stdout)
                    duration = float(info['format']['duration'])
                    if info.get('streams'):
                        width = info['streams'][0].get('width', 0)
                        height = info['streams'][0].get('height', 0)
                except:
                    pass
                
                jobs[job_id] = {
                    "status": "completed",
                    "progress": 100,
                    "message": "İndirme tamamlandı",
                    "video_path": str(output_file),
                    "duration": int(duration),
                    "width": width,
                    "height": height
                }
            else:
                jobs[job_id] = {"status": "error", "message": "İndirme başarısız - Dosya oluşturulamadı"}
                
        except Exception as e:
            jobs[job_id] = {"status": "error", "message": str(e)}
    
    threading.Thread(target=download_task).start()
    return jsonify({"success": True, "job_id": job_id})

@app.route('/api/job/<job_id>')
def get_job(job_id):
    return jsonify(jobs.get(job_id, {"error": "İş bulunamadı"}))

@app.route('/api/preview', methods=['POST'])
def extract_preview():
    data = request.json
    video_path = data.get('video_path')
    timestamp = data.get('timestamp', 600)
    
    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "Video bulunamadı"}), 404
    
    preview_id = str(uuid.uuid4())[:8]
    
    try:
        img_path = TEMP_FOLDER / f"{preview_id}.jpg"
        
        rel_video = os.path.relpath(video_path, BASE_DIR)
        rel_img = os.path.relpath(img_path, BASE_DIR)
        
        cmd_img = [
            'ffmpeg', '-y', '-nostdin', '-ss', str(timestamp),
            '-i', rel_video, '-vframes', '1', '-q:v', '1',
            '-vf', 'scale=iw:ih',
            rel_img
        ]
        subprocess.run(cmd_img, capture_output=True, check=True, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL)
        
        dim_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                   '-show_entries', 'stream=width,height', '-of', 'json', rel_video]
        dim_result = subprocess.run(dim_cmd, capture_output=True, text=True, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL)
        width, height = 1920, 1080
        try:
            dim_info = json.loads(dim_result.stdout)
            if dim_info.get('streams'):
                width = dim_info['streams'][0].get('width', 1920)
                height = dim_info['streams'][0].get('height', 1080)
        except:
            pass
        
        return jsonify({
            "success": True,
            "preview_id": preview_id,
            "image": f"/api/temp/{preview_id}.jpg",
            "video_width": width,
            "video_height": height
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/temp/<filename>')
def serve_temp(filename):
    return send_from_directory(TEMP_FOLDER, filename)

@app.route('/api/analyze', methods=['POST'])
def analyze_video():
    data = request.json
    video_path = data.get('video_path')
    
    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "Video bulunamadı"}), 404
    
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "analyzing", "progress": 0, "message": "Analiz başlıyor..."}
    
    def analyze_task():
        try:
            import random, hashlib
            
            rel_video = os.path.relpath(video_path, BASE_DIR)
            
            cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                   '-of', 'json', rel_video]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL)
            duration = float(json.loads(result.stdout)['format']['duration'])
            
            jobs[job_id]["message"] = "Ses analizi yapılıyor..."
            jobs[job_id]["progress"] = 30
            
            audio_path = TEMP_FOLDER / f"{job_id}.wav"
            rel_audio = os.path.relpath(audio_path, BASE_DIR)
            
            cmd = ['ffmpeg', '-y', '-nostdin', '-i', rel_video, '-vn', '-acodec', 'pcm_s16le',
                   '-ar', '16000', '-ac', '1', rel_audio]
            subprocess.run(cmd, capture_output=True, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL)
            
            jobs[job_id]["progress"] = 60
            jobs[job_id]["message"] = "Viral anlar tespit ediliyor..."
            
            rng = random.Random(time.time())
            
            clip_duration = 30
            safe_start = 30
            safe_end   = max(safe_start + clip_duration, duration - 30)
            usable     = safe_end - safe_start
            
            num_clips = min(10, max(4, int(duration / 45)))
            
            segment_size = usable / num_clips
            timestamps = []
            for i in range(num_clips):
                seg_start = safe_start + i * segment_size
                seg_end   = seg_start + segment_size - clip_duration
                if seg_end > seg_start:
                    ts = rng.uniform(seg_start, seg_end)
                else:
                    ts = seg_start
                timestamps.append(int(ts))
            
            rng.shuffle(timestamps)
            
            clip_types = ['laughter', 'excitement', 'reaction', 'scream', 'funny', 'viral', 'moment', 'epic']
            clips = []
            for i, ts in enumerate(timestamps):
                viral_score = rng.randint(70, 98)
                clips.append({
                    "id": f"clip_{job_id}_{i}",
                    "timestamp": ts,
                    "duration": clip_duration,
                    "viral_score": viral_score,
                    "type": clip_types[i % len(clip_types)]
                })
            
            if audio_path.exists():
                try: audio_path.unlink()
                except: pass
            
            jobs[job_id] = {
                "status": "completed",
                "progress": 100,
                "message": f"{len(clips)} viral an bulundu",
                "clips": sorted(clips, key=lambda x: x['viral_score'], reverse=True)
            }
            
        except Exception as e:
            jobs[job_id] = {"status": "error", "message": str(e)}
    
    threading.Thread(target=analyze_task).start()
    return jsonify({"success": True, "job_id": job_id})

@app.route('/api/generate', methods=['POST'])
def generate_shorts():
    data = request.json
    video_path = data.get('video_path')
    clips = data.get('clips', [])
    webcams = data.get('webcams', [])
    # Tek kamera için smart_shorts parametreleri
    top_ratio    = float(data.get('top_ratio',    0.42))
    mask_gameplay = bool(data.get('mask_gameplay', True))
    ae_style      = bool(data.get('ae_style',      True))

    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "Video bulunamadı"}), 404
    
    if not clips:
        return jsonify({"error": "Klip seçilmedi"}), 400
    
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "processing", "progress": 0, "message": "Başlatılıyor...", "outputs": []}
    
    def generate_task():
        try:
            outputs = []
            total = len(clips)
            
            for i, clip in enumerate(clips):
                progress = int((i / total) * 100)
                jobs[job_id]["progress"] = progress
                jobs[job_id]["message"] = f"Klip {i+1}/{total} işleniyor..."
                
                timestamp = clip.get('timestamp', 0)
                duration = clip.get('duration', 30)
                output_name = f"viral_short_{job_id}_{i+1:02d}.mp4"
                output_path = OUTPUT_FOLDER / output_name
                
                if webcams and len(webcams) == 1:
                    create_single_webcam_layout(
                        video_path, str(output_path), timestamp, duration, webcams[0],
                        top_ratio=top_ratio, mask_gameplay=mask_gameplay, ae_style=ae_style
                    )
                elif webcams and len(webcams) > 1:
                    create_perfect_layout(video_path, str(output_path), timestamp, duration, webcams)
                else:
                    extract_game_only(video_path, str(output_path), timestamp, duration)
                
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                
                outputs.append({
                    "id": f"{job_id}_{i}",
                    "name": output_name,
                    "path": str(output_path),
                    "url": f"/api/download/{output_name}",
                    "duration": duration,
                    "size": f"{size_mb:.1f} MB"
                })
            
            jobs[job_id] = {
                "status": "completed",
                "progress": 100,
                "message": f"{len(outputs)} shorts üretildi",
                "outputs": outputs
            }
            
        except Exception as e:
            jobs[job_id] = {"status": "error", "message": str(e)}
    
    threading.Thread(target=generate_task).start()
    return jsonify({"success": True, "job_id": job_id})


def create_perfect_layout(input_path, output_path, start_time, duration, webcams):
    import math

    OUTPUT_W     = 1080
    OUTPUT_H     = 1920
    CAM_CELL_W   = 540
    CAM_CELL_H   = 288
    WEBCAM_H     = 576
    GAME_W       = 1080
    GAME_H       = 1344

    num_webcams = min(len(webcams), 4)

    rel_input = os.path.relpath(input_path, BASE_DIR)
    rel_output = os.path.relpath(output_path, BASE_DIR)

    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height:format=duration', '-of', 'json', rel_input],
        capture_output=True, text=True, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL
    )
    orig_w, orig_h = 1920, 1080
    total_duration = None
    try:
        info = json.loads(probe.stdout)
        if info.get('streams'):
            orig_w = info['streams'][0].get('width',  1920)
            orig_h = info['streams'][0].get('height', 1080)
        if info.get('format', {}).get('duration'):
            total_duration = float(info['format']['duration'])
    except Exception:
        pass

    start_time = max(0, float(start_time))
    duration = max(1, float(duration))
    if total_duration and total_duration > 1:
        start_time = min(start_time, max(0, total_duration - 1))
        duration = min(duration, max(1, total_duration - start_time))

    def cover_dims(src_w, src_h, tw, th):
        scale = max(tw / src_w, th / src_h)
        sw = math.ceil(src_w * scale)
        sh = math.ceil(src_h * scale)
        sw = sw + (sw % 2)
        sh = sh + (sh % 2)
        return sw, sh

    parts = []

    if num_webcams > 0:
        max_y_end = 0
        for cam in webcams[:num_webcams]:
            y_end = float(cam.get('y', 0)) + float(cam.get('height', 20))
            max_y_end = max(max_y_end, y_end)
        game_start_pct = min(max_y_end + 0.5, 40.0)
    else:
        game_start_pct = 18.0

    g_start_y = max(0, min(int(orig_h * game_start_pct / 100), orig_h - 2))
    g_crop_h  = orig_h - g_start_y
    g_crop_h  = max(g_crop_h, orig_h // 4)
    g_crop_h  = min(g_crop_h, orig_h - g_start_y)

    gw, gh = cover_dims(orig_w, g_crop_h, GAME_W, GAME_H)
    cx_g = (gw - GAME_W) // 2
    cy_g = (gh - GAME_H) // 2

    parts.append(
        f"[0:v]crop={orig_w}:{g_crop_h}:0:{g_start_y},"
        f"scale={gw}:{gh},"
        f"crop={GAME_W}:{GAME_H}:{cx_g}:{cy_g}[game]"
    )

    for i in range(4):
        if i < num_webcams:
            cam   = webcams[i]
            x_pct = float(cam.get('x',      0))
            y_pct = float(cam.get('y',      0))
            w_pct = float(cam.get('width',  25))
            h_pct = float(cam.get('height', 25))

            cx = max(0, int(orig_w * x_pct / 100))
            cy = max(0, int(orig_h * y_pct / 100))
            cw = max(4, int(orig_w * w_pct / 100))
            ch = max(4, int(orig_h * h_pct / 100))

            cx = min(cx, orig_w - 4)
            cy = min(cy, orig_h - 4)
            cw = min(cw, orig_w - cx)
            ch = min(ch, orig_h - cy)

            sw, sh = cover_dims(cw, ch, CAM_CELL_W, CAM_CELL_H)
            ox = (sw - CAM_CELL_W) // 2
            oy = (sh - CAM_CELL_H) // 2

            parts.append(
                f"[0:v]crop={cw}:{ch}:{cx}:{cy},"
                f"scale={sw}:{sh},"
                f"crop={CAM_CELL_W}:{CAM_CELL_H}:{ox}:{oy}[cam{i}]"
            )
        else:
            parts.append(
                f"color=c=#111118:s={CAM_CELL_W}x{CAM_CELL_H}:r=30,trim=duration={duration}[cam{i}]"
            )

    parts.append("[cam0][cam1]hstack=inputs=2[row0]")
    parts.append("[cam2][cam3]hstack=inputs=2[row1]")
    parts.append("[row0][row1]vstack=inputs=2[camgrid]")
    parts.append("[camgrid][game]vstack=inputs=2[final]")

    filter_complex = ";".join(parts)

    SEEK_BUFFER = 3.0
    pre_seek = max(0.0, start_time - SEEK_BUFFER)
    accurate_offset = start_time - pre_seek

    cmd = [
        'ffmpeg', '-y', '-nostdin', '-nostats', '-loglevel', 'error',
        '-ss', str(pre_seek),
        '-i',  rel_input,
        '-ss', str(accurate_offset),
        '-t',  str(duration),
        '-filter_complex', filter_complex,
        '-map', '[final]',
        '-map', '0:a?',
        '-c:v',     'libx264',
        '-preset',  'fast',
        '-crf',     '17',
        '-profile:v','high',
        '-level',   '4.1',
        '-pix_fmt', 'yuv420p',
        '-c:a',     'aac',
        '-b:a',     '256k',
        '-ar',      '48000',
        '-ac',      '2',
        '-movflags','+faststart',
        rel_output
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR),
                                 stdin=subprocess.DEVNULL, timeout=180)
    except subprocess.TimeoutExpired:
        raise Exception("FFmpeg hatası: işlem zaman aşımına uğradı (180sn) - "
                         "kaynak video bozuk olabilir veya arama noktasında sorun var.")

    if result.returncode != 0:
        err = (result.stderr or "").strip() or "(ffmpeg boş hata döndürdü, dosya bozuk olabilir)"
        raise Exception(f"FFmpeg hatası: {err[-800:]}")
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        raise Exception("FFmpeg hatası: çıktı dosyası oluşmadı veya boş "
                         "(seçilen zaman aralığı video süresini aşıyor olabilir).")


def create_single_webcam_layout(input_path, output_path, start_time, duration, webcam,
                                top_ratio=0.42, mask_gameplay=True, ae_style=True):
    """
    Tek kamera layout — smart_shorts.py render_clip() ile birebir aynı mantık:
      - Üst bölge (top_ratio * 1920 yüksek): webcam ROI alanı, fill-crop ile tam doldurur
      - AE style: shadow + beyaz çerçeve efekti
      - Oyun: webcam alanı blur-patch ile gizlenir (mask_gameplay=True),
              contrast/saturation/unsharp renk düzeltmesi uygulanır
      - Alt bölge: oyun görüntüsü fill-crop ile tam doldurur
    """
    # --- Boyutlar (smart_shorts ile aynı hesap) ---
    top_ratio = float(max(0.20, min(0.70, top_ratio)))
    top_h = int(round(1920 * top_ratio))   # webcam yüksekliği (px)
    bot_h = 1920 - top_h                   # oyun yüksekliği (px)

    rel_input  = os.path.relpath(input_path,  BASE_DIR)
    rel_output = os.path.relpath(output_path, BASE_DIR)

    # --- Kaynak video boyutları + toplam süre ---
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height:format=duration', '-of', 'json', rel_input],
        capture_output=True, text=True, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL
    )
    orig_w, orig_h = 1920, 1080
    total_duration = None
    try:
        info = json.loads(probe.stdout)
        if info.get('streams'):
            orig_w = info['streams'][0].get('width',  1920)
            orig_h = info['streams'][0].get('height', 1080)
        if info.get('format', {}).get('duration'):
            total_duration = float(info['format']['duration'])
    except Exception:
        pass

    # --- start_time/duration video sınırlarını aşmasın (aşarsa ffmpeg 0 kare üretip takılabilir) ---
    start_time = max(0, float(start_time))
    duration = max(1, float(duration))
    if total_duration and total_duration > 1:
        start_time = min(start_time, max(0, total_duration - 1))
        duration = min(duration, max(1, total_duration - start_time))

    # --- Webcam crop koordinatları (ROI yüzdeleri → piksel) ---
    x_pct = float(webcam.get('x',      0))
    y_pct = float(webcam.get('y',      0))
    w_pct = float(webcam.get('width',  25))
    h_pct = float(webcam.get('height', 25))

    wx = max(0, int(orig_w * x_pct / 100))
    wy = max(0, int(orig_h * y_pct / 100))
    ww = max(4, int(orig_w * w_pct / 100))
    wh = max(4, int(orig_h * h_pct / 100))
    wx = min(wx, orig_w - 4)
    wy = min(wy, orig_h - 4)
    ww = min(ww, orig_w - wx)
    wh = min(wh, orig_h - wy)

    # --- CAM: fill-crop (scale to increase, then crop center) — smart_shorts ile aynı ---
    cam_chain = (
        f"[0:v]"
        f"crop={ww}:{wh}:{wx}:{wy},"
        f"scale=1080:{top_h}:force_original_aspect_ratio=increase,"
        f"crop=1080:{top_h},format=rgba[cam];"
    )

    # --- AE style: shadow + beyaz çerçeve (smart_shorts ae_style=True ile aynı) ---
    if ae_style:
        cam_fx = (
            f"[cam]split=2[c0][c1];"
            f"[c1]colorchannelmixer=aa=0.35,gblur=sigma=12[sh];"
            f"color=c=black@0.0:size=1080x{top_h}[bg];"
            f"[bg][sh]overlay=8:8[tmp];"
            f"[tmp][c0]overlay=0:0,drawbox=x=12:y=12:w=iw-24:h=ih-24:color=white@0.65:t=6[top];"
        )
    else:
        cam_fx = "[cam]copy[top];"

    # --- GAME BOTTOM: webcam alanını blur ile maskele (smart_shorts mask_gameplay ile aynı) ---
    color_correct = ",eq=contrast=1.06:saturation=1.08,unsharp=5:5:0.6:5:5:0.0" if ae_style else ""
    if mask_gameplay:
        bottom_chain = (
            f"[0:v]split=2[g0][gpatch];"
            f"[gpatch]crop={ww}:{wh}:{wx}:{wy},boxblur=12:2[blur];"
            f"[g0][blur]overlay={wx}:{wy}[g1];"
            f"[g1]scale=1080:{bot_h}:force_original_aspect_ratio=increase,"
            f"crop=1080:{bot_h}"
            f"{color_correct}"
            f"[bottom];"
        )
    else:
        bottom_chain = (
            f"[0:v]"
            f"scale=1080:{bot_h}:force_original_aspect_ratio=increase,"
            f"crop=1080:{bot_h}"
            f"{color_correct}"
            f"[bottom];"
        )

    filter_complex = (
        cam_chain +
        cam_fx +
        bottom_chain +
        "[top][bottom]vstack=inputs=2[final]"
    )

    # --- Hibrit arama: bozuk/HLS-birleştirilmiş dosyalarda decoder'ın takılmasını önler ---
    SEEK_BUFFER = 3.0
    pre_seek = max(0.0, start_time - SEEK_BUFFER)
    accurate_offset = start_time - pre_seek

    cmd = [
        'ffmpeg', '-y', '-nostdin', '-nostats', '-loglevel', 'error',
        '-ss', str(pre_seek),
        '-i',  rel_input,
        '-ss', str(accurate_offset),
        '-t',  str(duration),
        '-filter_complex', filter_complex,
        '-map', '[final]',
        '-map', '0:a?',
        '-c:v',      'libx264',
        '-preset',   'veryfast',
        '-crf',      '18',
        '-pix_fmt',  'yuv420p',
        '-c:a',      'aac',
        '-b:a',      '160k',
        '-movflags', '+faststart',
        rel_output
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR),
                                 stdin=subprocess.DEVNULL, timeout=180)
    except subprocess.TimeoutExpired:
        raise Exception("FFmpeg hatası (tek kamera): işlem zaman aşımına uğradı (180sn) - "
                         "kaynak video bozuk olabilir veya arama noktasında sorun var.")

    if result.returncode != 0:
        err = (result.stderr or "").strip() or "(ffmpeg boş hata döndürdü, dosya bozuk olabilir)"
        raise Exception(f"FFmpeg hatası (tek kamera): {err[-800:]}")
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        raise Exception("FFmpeg hatası (tek kamera): çıktı dosyası oluşmadı veya boş "
                         "(seçilen zaman aralığı video süresini aşıyor olabilir).")


def extract_game_only(input_path, output_path, start_time, duration):
    rel_input = os.path.relpath(input_path, BASE_DIR)
    rel_output = os.path.relpath(output_path, BASE_DIR)

    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', rel_input],
        capture_output=True, text=True, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL
    )
    total_duration = None
    try:
        info = json.loads(probe.stdout)
        if info.get('format', {}).get('duration'):
            total_duration = float(info['format']['duration'])
    except Exception:
        pass

    start_time = max(0, float(start_time))
    duration = max(1, float(duration))
    if total_duration and total_duration > 1:
        start_time = min(start_time, max(0, total_duration - 1))
        duration = min(duration, max(1, total_duration - start_time))

    SEEK_BUFFER = 3.0
    pre_seek = max(0.0, start_time - SEEK_BUFFER)
    accurate_offset = start_time - pre_seek

    cmd = [
        'ffmpeg', '-y', '-nostdin', '-nostats', '-loglevel', 'error',
        '-ss', str(pre_seek),
        '-i', rel_input,
        '-ss', str(accurate_offset),
        '-t', str(duration),
        '-vf', (
            'scale=1080:1920:force_original_aspect_ratio=decrease,'
            'pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black'
        ),
        '-c:v', 'libx264',
        '-preset', 'slow',
        '-crf', '16',
        '-profile:v', 'high',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        '-b:a', '320k',
        '-ar', '48000',
        '-movflags', '+faststart',
        rel_output
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR),
                                 stdin=subprocess.DEVNULL, timeout=180)
    except subprocess.TimeoutExpired:
        raise Exception("Video üretim hatası: işlem zaman aşımına uğradı (180sn) - "
                         "kaynak video bozuk olabilir veya arama noktasında sorun var.")

    if result.returncode != 0:
        err = (result.stderr or "").strip() or "(ffmpeg boş hata döndürdü, dosya bozuk olabilir)"
        raise Exception(f"Video üretim hatası: {err[-800:]}")
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        raise Exception("Video üretim hatası: çıktı dosyası oluşmadı veya boş "
                         "(seçilen zaman aralığı video süresini aşıyor olabilir).")


@app.route('/api/download/<filename>')
def download_file(filename):
    file_path = OUTPUT_FOLDER / filename
    if file_path.exists():
        return send_file(file_path, as_attachment=True)
    return jsonify({"error": "Dosya bulunamadı"}), 404

@app.route('/api/cleanup', methods=['POST'])
def cleanup():
    try:
        now = time.time()
        for folder in [TEMP_FOLDER, UPLOAD_FOLDER]:
            for f in folder.glob("*"):
                if f.is_file() and (now - f.stat().st_mtime) > 3600:
                    f.unlink()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    
    print("=" * 60)
    print("  Viral Shorts Generator - Professional Edition")
    print("=" * 60)
    print()
    
    ffmpeg_ok = shutil.which('ffmpeg') is not None
    ytdlp_ok = shutil.which('yt-dlp') is not None
    
    if ffmpeg_ok:
        print("✅ FFmpeg kurulu")
    else:
        print("❌ FFmpeg bulunamadı!")
        print("   Kurulum: https://ffmpeg.org/download.html")
    
    if ytdlp_ok:
        print("✅ yt-dlp kurulu")
    else:
        print("❌ yt-dlp bulunamadı!")
        print("   Kurulum: pip install yt-dlp")
    
    if not (ffmpeg_ok and ytdlp_ok):
        print()
        print("Gerekli bağımlılıklar eksik!")
        sys.exit(1)
    
    print()
    print(f"🌐 Sunucu başlatılıyor: http://localhost:{args.port}")
    print(f"📁 Uploads: {UPLOAD_FOLDER}")
    print(f"📁 Outputs: {OUTPUT_FOLDER}")
    print()
    
    app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)
