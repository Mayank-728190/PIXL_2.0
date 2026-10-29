from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone, timedelta

from pixl.core.database import get_db_session
from pixl.core.config import settings
from pixl.modules.screens.models import Screen
from pixl.modules.media.models import MediaAsset
from pixl.modules.playlists.models import Playlist, PlaylistItem
from pixl.modules.campaigns.models import Campaign, ScreenAssignment

def require_simulator_enabled():
    if settings.ENVIRONMENT == "production" or not settings.ALLOW_LEGACY_TV:
        raise HTTPException(404, "Browser simulator is not available")


simulator_router = APIRouter(tags=["Simulator: Browser Screen Player"],
                             dependencies=[Depends(require_simulator_enabled)])


SIMULATOR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PIXL 2.0 Screen Simulator</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body, html {
      width: 100%; height: 100%;
      background: #000;
      color: #fff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      overflow: hidden;
    }
    #screen-viewport {
      width: 100vw; height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      background: #000;
    }
    .media-container {
      width: 100%; height: 100%;
      position: absolute;
      top: 0; left: 0;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    video, img {
      width: 100%; height: 100%;
      object-fit: contain;
      display: none;
    }
    .active-media {
      display: block !important;
    }
    /* Kiosk Notice Banner */
    #kiosk-notice {
      position: absolute;
      top: 0; left: 0; right: 0;
      background: rgba(220, 38, 38, 0.9);
      color: #fff;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      padding: 6px 16px;
      text-align: center;
      z-index: 100;
      backdrop-filter: blur(4px);
    }
    /* Screen HUD */
    #screen-hud {
      position: absolute;
      bottom: 20px; left: 20px;
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 10px;
      padding: 14px 18px;
      font-size: 13px;
      z-index: 90;
      min-width: 280px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      transition: opacity 0.3s;
    }
    #screen-hud h3 {
      font-size: 14px;
      font-weight: 700;
      margin-bottom: 6px;
      color: #60a5fa;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .badge {
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 4px;
      background: #10b981;
      color: #fff;
      text-transform: uppercase;
    }
    .badge.unpaired { background: #f59e0b; }
    .hud-row {
      display: flex;
      justify-content: space-between;
      margin-top: 4px;
      color: #94a3b8;
    }
    .hud-val { color: #f1f5f9; font-weight: 500; }
    .progress-bar-wrap {
      width: 100%;
      height: 4px;
      background: rgba(255, 255, 255, 0.15);
      border-radius: 2px;
      margin-top: 10px;
      overflow: hidden;
    }
    #progress-bar {
      width: 0%;
      height: 100%;
      background: #3b82f6;
      transition: width 0.2s linear;
    }
    /* Pairing Overlay */
    #pairing-overlay {
      position: absolute;
      top: 0; left: 0; width: 100%; height: 100%;
      background: #0f172a;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      z-index: 80;
    }
    .pin-box {
      background: #1e293b;
      border: 2px dashed #3b82f6;
      border-radius: 12px;
      padding: 24px 48px;
      text-align: center;
      margin: 20px 0;
    }
    .pin-digits {
      font-family: monospace;
      font-size: 56px;
      font-weight: 800;
      letter-spacing: 12px;
      color: #60a5fa;
    }
    button {
      background: #3b82f6;
      border: none;
      color: white;
      padding: 10px 20px;
      border-radius: 6px;
      cursor: pointer;
      font-weight: 600;
      margin-top: 12px;
    }
    button:hover { background: #2563eb; }
    /* Top Toolbar */
    #top-toolbar {
      position: absolute;
      top: 36px; right: 20px;
      display: flex;
      gap: 8px;
      z-index: 95;
    }
    .btn-tool {
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.2);
      color: #cbd5e1;
      padding: 6px 12px;
      font-size: 12px;
      border-radius: 6px;
      cursor: pointer;
    }
    .btn-tool:hover { background: rgba(30, 41, 59, 0.9); color: #fff; }
  </style>
</head>
<body>
  <div id="kiosk-notice">
    DEVELOPMENT PREVIEW: Browser fullscreen preview is for local agency QA & testing. It is not equivalent to Android Kiosk / Lock Task Mode.
  </div>

  <div id="top-toolbar">
    <button class="btn-tool" onclick="toggleMute()" id="mute-btn">Unmute Audio</button>
    <button class="btn-tool" onclick="toggleFullscreen()">Fullscreen</button>
    <button class="btn-tool" onclick="manualSync()">Sync Now</button>
  </div>

  <div id="screen-viewport">
    <div id="pairing-overlay" style="display: none;">
      <h2 style="font-size: 26px; font-weight: 700; margin-bottom: 8px;">Connect This Screen</h2>
      <p style="color: #94a3b8; font-size: 14px;">Enter this pairing PIN in your Agency Dashboard to activate ad playback.</p>
      <div class="pin-box">
        <div style="font-size: 12px; text-transform: uppercase; color: #94a3b8; margin-bottom: 8px;">Registration PIN</div>
        <div class="pin-digits" id="pin-display">------</div>
      </div>
      <p id="pairing-screen-id" style="font-size: 13px; color: #64748b;">Screen ID: ...</p>
      <button onclick="checkAssignment()">I Have Paired In Dashboard</button>
    </div>

    <div class="media-container">
      <video id="player-video" playsinline></video>
      <img id="player-image" alt="Digital Signage Asset" />
    </div>

    <div id="screen-hud">
      <h3>
        <span id="hud-screen-name">PIXL Virtual Screen</span>
        <span id="hud-status-badge" class="badge">ACTIVE</span>
      </h3>
      <div class="hud-row"><span>Screen ID:</span><span id="hud-screen-id" class="hud-val">...</span></div>
      <div class="hud-row"><span>Campaign:</span><span id="hud-campaign-name" class="hud-val">Waiting...</span></div>
      <div class="hud-row"><span>Ad Item:</span><span id="hud-ad-name" class="hud-val">...</span></div>
      <div class="hud-row"><span>Proof of Play Count:</span><span id="hud-pop-count" class="hud-val">0</span></div>
      <div class="progress-bar-wrap">
        <div id="progress-bar"></div>
      </div>
    </div>
  </div>

  <script>
    let state = {
      screenId: localStorage.getItem('pixl_sim_screen_id') || null,
      pairingCode: localStorage.getItem('pixl_sim_pin') || null,
      isPaired: false,
      currentCampaign: null,
      playlist: [],
      currentIndex: 0,
      itemTimer: null,
      itemTimeRemaining: 0,
      totalDuration: 0,
      isMuted: true,
      popCount: 0
    };

    const videoEl = document.getElementById('player-video');
    const imageEl = document.getElementById('player-image');
    videoEl.muted = true;

    async function init() {
      if (!state.screenId || !state.pairingCode) {
        await registerScreen();
      } else {
        await sync();
      }
      setInterval(sync, 10000); // Periodic sync matches Android workflow
    }

    async function registerScreen() {
      try {
        const res = await fetch('/api/tv/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: 'Browser Simulator Screen ' + Math.floor(Math.random() * 1000),
            location: 'Browser Dev Environment'
          })
        });
        const data = await res.json();
        state.screenId = data.screenId;
        state.pairingCode = data.pairingCode;
        localStorage.setItem('pixl_sim_screen_id', state.screenId);
        localStorage.setItem('pixl_sim_pin', state.pairingCode);
        showPairing();
      } catch (e) {
        console.error('Registration failed', e);
      }
    }

    function showPairing() {
      document.getElementById('pairing-overlay').style.display = 'flex';
      document.getElementById('pin-display').innerText = state.pairingCode || '------';
      document.getElementById('pairing-screen-id').innerText = 'Screen ID: ' + state.screenId;
      document.getElementById('hud-status-badge').innerText = 'UNPAIRED';
      document.getElementById('hud-status-badge').className = 'badge unpaired';
    }

    async function checkAssignment() {
      if (!state.pairingCode) return;
      try {
        const res = await fetch(`/api/tv/player/${state.pairingCode}/assignment`);
        const data = await res.json();
        if (data.isPaired) {
          state.isPaired = true;
          document.getElementById('pairing-overlay').style.display = 'none';
          document.getElementById('hud-status-badge').innerText = 'ACTIVE';
          document.getElementById('hud-status-badge').className = 'badge';
          await sync();
        } else {
          alert('PIN ' + state.pairingCode + ' has not been claimed yet in the Agency dashboard. Please claim PIN and try again.');
        }
      } catch (e) {
        console.error('Check assignment failed', e);
      }
    }

    async function sync() {
      if (!state.screenId || !state.pairingCode) return;
      try {
        const res = await fetch(`/api/tv/sync?screenId=${state.screenId}&pairingCode=${state.pairingCode}`);
        const data = await res.json();
        if (!data.isPaired) {
          showPairing();
          return;
        }
        document.getElementById('pairing-overlay').style.display = 'none';
        document.getElementById('hud-screen-id').innerText = state.screenId;
        document.getElementById('hud-status-badge').innerText = 'ACTIVE';
        document.getElementById('hud-status-badge').className = 'badge';

        if (data.campaign && data.campaign.playlist && data.campaign.playlist.mediaItems.length > 0) {
          const newCampId = data.campaign.id;
          const oldCampId = state.currentCampaign ? state.currentCampaign.id : null;
          if (newCampId !== oldCampId) {
            state.currentCampaign = data.campaign;
            state.playlist = data.campaign.playlist.mediaItems;
            state.currentIndex = 0;
            document.getElementById('hud-campaign-name').innerText = data.campaign.name || 'Ad Campaign';
            playCurrentItem();
          }
        } else {
          document.getElementById('hud-campaign-name').innerText = 'No Active Ad Scheduled';
          videoEl.style.display = 'none';
          imageEl.style.display = 'none';
        }
      } catch (e) {
        console.error('Sync failed', e);
      }
    }

    function playCurrentItem() {
      if (!state.playlist || state.playlist.length === 0) return;
      clearTimeout(state.itemTimer);

      const item = state.playlist[state.currentIndex % state.playlist.length];
      document.getElementById('hud-ad-name').innerText = item.filename || item.name;
      const duration = (item.durationSeconds || 10) * 1000;
      state.totalDuration = duration;
      state.itemTimeRemaining = duration;

      const startTime = Date.now();
      const progressEl = document.getElementById('progress-bar');

      const progressInterval = setInterval(() => {
        const elapsed = Date.now() - startTime;
        const pct = Math.min(100, (elapsed / duration) * 100);
        progressEl.style.width = pct + '%';
        if (elapsed >= duration) {
          clearInterval(progressInterval);
        }
      }, 100);

      if (item.type === 'video') {
        imageEl.style.display = 'none';
        videoEl.style.display = 'block';
        videoEl.src = item.publicUrl;
        videoEl.currentTime = 0;
        videoEl.play().catch(e => console.log('Autoplay muted requirement', e));
      } else {
        videoEl.style.display = 'none';
        videoEl.pause();
        imageEl.style.display = 'block';
        imageEl.src = item.publicUrl;
      }

      state.itemTimer = setTimeout(async () => {
        // Record Proof of Play
        await recordProofOfPlay(item);
        // Advance to next ad
        state.currentIndex = (state.currentIndex + 1) % state.playlist.length;
        playCurrentItem();
      }, duration);
    }

    async function recordProofOfPlay(item) {
      if (!state.screenId || !state.currentCampaign) return;
      try {
        const receipt = [{
          mediaId: item.id,
          campaignId: String(state.currentCampaign.id),
          durationSeconds: item.durationSeconds || 10,
          timestamp: Date.now(),
          status: 'COMPLETED'
        }];
        await fetch(`/api/tv/${state.screenId}/proof-of-play?pairingCode=${encodeURIComponent(state.pairingCode)}`,  {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(receipt)
        });
        state.popCount++;
        document.getElementById('hud-pop-count').innerText = state.popCount;
      } catch (e) {
        console.error('PoP submit error', e);
      }
    }

    function toggleMute() {
      state.isMuted = !state.isMuted;
      videoEl.muted = state.isMuted;
      document.getElementById('mute-btn').innerText = state.isMuted ? 'Unmute Audio' : 'Mute Audio';
    }

    function toggleFullscreen() {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(e => {});
      } else {
        document.exitFullscreen().catch(e => {});
      }
    }

    function manualSync() {
      sync();
    }

    window.onload = init;
  </script>
</body>
</html>
"""


@simulator_router.get("/simulator", response_class=HTMLResponse)
async def screen_simulator_page():
    """
    Lightweight Browser Screen Simulator.
    Implements the exact same sync, manifest loading, and proof-of-play engine
    as the native Android Player, enabling instant local agency ad playback testing.
    """
    return HTMLResponse(content=SIMULATOR_HTML, status_code=200)


@simulator_router.get("/player", response_class=RedirectResponse)
async def player_alias():
    return RedirectResponse(url="/simulator")

