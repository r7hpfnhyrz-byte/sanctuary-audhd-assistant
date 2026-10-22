/* ==========================================================================
   Sanctuary • Interactive Client Controller for AuDHD Assistant & Coach
   Direct Deep-Link & 1-Click Launch + Auto-Complete Engine
   ========================================================================== */

const App = {
  state: {
    briefing: null,
    selectedHorizon: '1d',
    emails: [],
    ideas: [],
    vault: null,
    selectedVaultWindow: 'week',
    pinnedTask: null,
    timerSeconds: 15 * 60,
    timerRunning: false,
    timerInterval: null,
  },

  async init() {
    await Promise.all([
      this.loadBriefing(),
      this.loadEmails(),
      this.loadIdeas(),
      this.loadVault('week'),
      this.loadCoachMessages(),
    ]);
  },

  async api(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    return res.json();
  },

  /* ------------------------------------------------------------------------
     DOPAMINE TOASTS, CONFETTI & AUDIO FEEDBACK
     ------------------------------------------------------------------------ */
  showToast(message) {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = 'dopamine-toast';
    el.innerHTML = message;
    container.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    }, 4200);
  },

  playChime(isBoss = false) {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const notes = isBoss ? [523.25, 659.25, 783.99, 1046.5] : [587.33, 880];
      notes.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.08, ctx.currentTime + idx * 0.09);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + idx * 0.09 + 0.35);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(ctx.currentTime + idx * 0.09);
        osc.stop(ctx.currentTime + idx * 0.09 + 0.36);
      });
    } catch (_) {}
  },

  burstConfetti() {
    const canvas = document.getElementById('confetti-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    const pieces = Array.from({ length: 65 }, () => ({
      x: canvas.width / 2 + (Math.random() - 0.5) * 180,
      y: canvas.height / 3,
      vx: (Math.random() - 0.5) * 12,
      vy: -Math.random() * 10 - 4,
      size: Math.random() * 7 + 4,
      color: ['#2d6a4f', '#eab308', '#6366f1', '#ec4899', '#10b981'][Math.floor(Math.random() * 5)],
      alpha: 1,
    }));

    let frame = 0;
    const animate = () => {
      frame++;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      pieces.forEach((p) => {
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.32;
        p.alpha = Math.max(0, 1 - frame / 65);
        ctx.fillStyle = p.color;
        ctx.globalAlpha = p.alpha;
        ctx.fillRect(p.x, p.y, p.size, p.size);
      });
      if (frame < 65) requestAnimationFrame(animate);
      else ctx.clearRect(0, 0, canvas.width, canvas.height);
    };
    requestAnimationFrame(animate);
  },

  /* ------------------------------------------------------------------------
     DIRECT TARGET LAUNCHER & 1-CLICK AUTO-COMPLETE ENGINE
     ------------------------------------------------------------------------ */
  async launchAndCompleteSuggestion(id, isBoss = false, autoComplete = true) {
    const res = await this.api('/api/actions/launch-and-complete', 'POST', {
      id,
      auto_complete: autoComplete,
    });
    if (!res.ok) return;

    const launched = res.launched || {};
    // If target is internal #inbox tab, switch immediately
    if (launched.target_url === '#inbox') {
      this.switchTab('inbox');
    } else if (!launched.opened_locally && launched.target_url && launched.target_url.startsWith('http')) {
      window.open(launched.target_url, '_blank', 'noopener');
    }

    if (launched.opened_locally) {
      this.showToast(`📂 Opened "${this.escape(launched.file_basename)}" directly from your Google Drive!`);
    } else if (res.inline_effect) {
      this.showToast(`⚡ ${this.escape(res.inline_effect)}`);
    }

    if (autoComplete) {
      this.clearPinnedTask();
      this.playChime(isBoss);
      if (isBoss) this.burstConfetti();
      this.updateHUD(res.progress);
      await this.loadBriefing();
      await this.loadVault(this.state.selectedVaultWindow);
    } else if (res.pinned_item) {
      this.pinActiveTask(res.pinned_item, isBoss);
    }
  },

  async openDirectTarget(localFilePath, targetUrl, label = 'Target') {
    if (targetUrl === '#inbox') {
      this.switchTab('inbox');
      return;
    }
    if (targetUrl === '#sandbox') {
      this.switchTab('sandbox');
      return;
    }
    const res = await this.api('/api/actions/open-target', 'POST', {
      local_file_path: localFilePath || '',
      target_url: targetUrl || '',
    });
    const launched = (res && res.launched) || {};
    if (launched.opened_locally) {
      this.showToast(`📂 Opened "${this.escape(launched.file_basename || label)}" on your Mac!`);
    } else if (targetUrl && targetUrl.startsWith('http')) {
      window.open(targetUrl, '_blank', 'noopener');
    }
  },

  pinActiveTask(item, isBoss = false) {
    this.state.pinnedTask = item;
    const bar = document.getElementById('pinned-task-bar');
    bar.classList.remove('hidden');
    document.getElementById('pinned-task-title').textContent = item.title;
    document.getElementById('pinned-task-target').textContent = `(${item.target_label || 'Opened'})`;

    document.getElementById('pinned-complete-btn').onclick = async () => {
      await this.completeSuggestion(item.id, isBoss);
      this.clearPinnedTask();
    };
    document.getElementById('pinned-reopen-btn').onclick = () => {
      this.openDirectTarget(item.local_file_path, item.target_url, item.target_label);
    };
  },

  clearPinnedTask() {
    this.state.pinnedTask = null;
    const bar = document.getElementById('pinned-task-bar');
    if (bar) bar.classList.add('hidden');
  },

  /* ------------------------------------------------------------------------
     HUD & ENERGY / SPOON CAPACITY SWITCHER
     ------------------------------------------------------------------------ */
  updateHUD(progress) {
    if (!progress) return;
    document.getElementById('hud-level').textContent = `Lv ${progress.level} • ${progress.level_title}`;
    const shieldIcon = progress.grace_shield_active_today ? '🛡️ Grace Shield Active' : '🛡️';
    document.getElementById('hud-streak').innerHTML = `🔥 ${progress.momentum_days}d ${shieldIcon}`;
    document.getElementById('hud-xp-fill').style.width = `${progress.xp_in_current_level}%`;
    document.getElementById('hud-xp-text').textContent = `${progress.xp} XP`;
    document.getElementById('hud-next-xp').textContent = `${progress.xp_to_next_level} XP to Lv ${progress.level + 1}`;

    document.querySelectorAll('.spoon-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.mode === progress.energy_mode);
    });

    const badgesRow = document.getElementById('vault-badges-row');
    if (badgesRow && progress.badges) {
      badgesRow.innerHTML = progress.badges
        .map((b) => `<span class="badge-chip" title="${this.escape(b.desc)}">${b.icon} ${this.escape(b.name)}</span>`)
        .join('');
    }

    if (progress.last_reward) {
      const r = progress.last_reward;
      const sparkText = r.mystery_spark_bonus ? ` (+${r.mystery_spark_bonus} Mystery Spark Bonus!)` : '';
      const lvlText = r.leveled_up ? ` 🎉 LEVEL UP TO LV ${r.new_level}!` : '';
      this.showToast(`✨ +${r.xp_gained} XP${sparkText} — ${this.escape(r.reason)}${lvlText}`);
    }
  },

  async setEnergyMode(mode) {
    const res = await this.api('/api/energy-mode', 'POST', { mode });
    if (res.ok) {
      this.state.briefing = res.briefing;
      this.updateHUD(res.progress);
      this.renderBriefing();
      await this.loadEmails();
      if (res.progress.grace_shield_just_activated) {
        this.playChime(false);
        this.showToast('🛡️ Low Spoons Grace Shield Activated! +20 XP for listening to your nervous system. Non-urgent clutter hidden.');
      } else {
        this.showToast(`Brain State switched to ${mode.replace('_', ' ').toUpperCase()}`);
      }
    }
  },

  switchTab(tabId) {
    document.querySelectorAll('.nav-tab').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-view').forEach((view) => {
      view.classList.toggle('active', view.id === `tab-${tabId}`);
    });
    if (tabId === 'vault') this.loadVault(this.state.selectedVaultWindow);
  },

  toggleTheme() {
    const html = document.documentElement;
    const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    document.getElementById('theme-toggle-btn').textContent = next === 'dark' ? '☀️' : '🌙';
  },

  /* ------------------------------------------------------------------------
     60-SECOND QUICK-WIN ROULETTE (1-Click Launch & Auto-Complete!)
     ------------------------------------------------------------------------ */
  async spinRoulette() {
    const res = await this.api('/api/roulette', 'POST');
    if (!res.ok) return;
    const spin = res.roulette;
    const banner = document.getElementById('roulette-banner');
    banner.classList.remove('hidden');
    document.getElementById('roulette-headline').textContent = `${spin.headline}`;
    document.getElementById('roulette-action').textContent = spin.micro_action;

    const doBtn = document.getElementById('roulette-do-btn');
    doBtn.textContent = spin.button_label || `🚀 Do & Auto-Complete (+${spin.xp_reward} XP)`;
    doBtn.onclick = async () => {
      banner.classList.add('hidden');
      if (spin.type === 'email' && spin.id) {
        await this.sendEmailDraft(spin.id, 'send', spin.draft_reply);
      } else if (spin.type === 'suggestion' && spin.id) {
        await this.launchAndCompleteSuggestion(spin.id, false, true);
      } else {
        const claim = await this.api('/api/roulette/claim-instant', 'POST', {
          xp: spin.xp_reward,
          reason: spin.headline,
        });
        this.playChime(false);
        this.updateHUD(claim.progress);
      }
    };
  },

  closeRoulette() {
    document.getElementById('roulette-banner').classList.add('hidden');
  },

  /* ------------------------------------------------------------------------
     VIEW 1: DAILY BRIEFING & 4-HORIZON RADAR
     ------------------------------------------------------------------------ */
  async loadBriefing() {
    const data = await this.api('/api/briefing');
    this.state.briefing = data;
    this.updateHUD(data.progress);
    this.renderBriefing();
  },

  renderBriefing() {
    const b = this.state.briefing;
    if (!b) return;

    document.getElementById('current-date-label').textContent = `${b.generated_at} • Multi-Account AuDHD Coach`;
    document.getElementById('briefing-headline').innerHTML = this.formatBold(b.coach_headline);

    // Clickable Connected Account Chips
    const accStrip = document.getElementById('connected-accounts-strip');
    accStrip.innerHTML = (b.connected_accounts || [])
      .map(
        (a) => `
        <span class="account-chip clickable" onclick="App.openDirectTarget('', '${this.escapeAttr(a.portal_url || 'https://www.notion.so')}', '${this.escapeAttr(a.account_label)}')" title="Click to open ${this.escape(a.account_label)}">
          <span class="account-dot" style="background:${a.color_tag}"></span>
          ${this.escape(a.account_label)} ↗
        </span>`
      )
      .join('');

    // Sensory weather
    const sw = b.sensory_weather || {};
    document.getElementById('weather-social-val').textContent = `${sw.social_load_score} / 10`;
    document.getElementById('weather-social-fill').style.width = `${Math.min(100, sw.social_load_score * 10)}%`;
    document.getElementById('weather-cog-val').textContent = `${sw.cognitive_load_score} / 10`;
    document.getElementById('weather-cog-fill').style.width = `${Math.min(100, sw.cognitive_load_score * 10)}%`;
    document.getElementById('weather-status-label').textContent = sw.status_label || '';

    // Daily Boss Card with 1-Click File Launch & Auto-Complete
    const bossContainer = document.getElementById('daily-boss-container');
    if (b.daily_boss) {
      const boss = b.daily_boss;
      const stepsHtml = (boss.micro_steps || [])
        .map((s) => `<li>${this.escape(s)}</li>`)
        .join('');
      const actionLabel = boss.inline_action_label || `🚀 Open Target & Auto-Complete (+${boss.xp_reward} XP)`;
      bossContainer.innerHTML = `
        <div class="daily-boss-card">
          <div style="flex:1; min-width:280px;">
            <div class="boss-badge">⚔️ TODAY'S DAILY BOSS • 3× DOPAMINE BONUS (+${boss.xp_reward} XP)</div>
            <div>
              <button class="target-link-pill" onclick="App.launchAndCompleteSuggestion(${boss.id}, true, false)" title="Opens the actual file and pins a 1-click Done bar at the top">
                🔗 ${this.escape(boss.target_label || 'Open Linked File')} ↗
              </button>
            </div>
            <h3 class="boss-title clickable-title" onclick="App.launchAndCompleteSuggestion(${boss.id}, true, true)" title="Click to open file & auto-complete!">
              ${this.escape(boss.title)} ↗
            </h3>
            <p class="boss-why">${this.escape(boss.why_it_matters)}</p>
            <div class="starter-step-box">
              <strong>90-Second Friction-Free Starter:</strong> ${this.escape(boss.starter_micro_step)}
            </div>
            ${stepsHtml ? `<ol class="micro-steps-list">${stepsHtml}</ol>` : ''}
          </div>
          <div class="card-actions-row" style="align-self:center; flex-direction:column; align-items:stretch;">
            <button class="btn-primary" onclick="App.launchAndCompleteSuggestion(${boss.id}, true, true)">
              ${this.escape(actionLabel)}
            </button>
            <button class="btn-secondary" onclick="App.launchAndCompleteSuggestion(${boss.id}, true, false)">
              ↗ Open File &amp; Pin Floating 'Done' Bar
            </button>
            <button class="btn-ghost" onclick="App.breakSuggestionSteps(${boss.id})">
              ✨ Shrink Into Smaller Micro-Steps
            </button>
          </div>
        </div>
      `;
    } else {
      bossContainer.innerHTML = `
        <div class="daily-boss-card">
          <div>
            <div class="boss-badge" style="background:var(--accent-primary);">🏆 DAILY BOSS DEFEATED!</div>
            <h3 class="boss-title">You already conquered today's biggest mental open loop!</h3>
            <p class="boss-why">Everything else today is bonus momentum. Check your Accomplishment Vault whenever you want a reminder of your progress.</p>
          </div>
        </div>
      `;
    }

    // Horizon counts
    ['1d', '2d', '1w', '1m'].forEach((h) => {
      const count = ((b.horizons && b.horizons[h]) || []).length;
      const el = document.getElementById(`h-count-${h}`);
      if (el) el.textContent = count;
    });

    this.renderSelectedHorizon();
  },

  selectHorizon(horizon) {
    this.state.selectedHorizon = horizon;
    document.querySelectorAll('[data-horizon]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.horizon === horizon);
    });
    this.renderSelectedHorizon();
  },

  renderSelectedHorizon() {
    const b = this.state.briefing;
    if (!b) return;
    const h = this.state.selectedHorizon;
    const labels = {
      '1d': 'Today (Next 24 Hours)',
      '2d': 'Tomorrow & 48-Hour Lookahead',
      '1w': 'Next 7 Days Capacity & Bottleneck Radar',
      '1m': 'Next 30 Days Long-Range Radar',
    };
    document.getElementById('horizon-prep-heading').textContent = `Proactive Prep & Direct Launch • ${labels[h]}`;
    document.getElementById('horizon-cal-heading').textContent = `Schedule & Linked Docs • ${labels[h]}`;

    const suggestions = (b.horizons && b.horizons[h]) || [];
    const suggList = document.getElementById('horizon-suggestions-list');
    if (suggestions.length === 0) {
      suggList.innerHTML = `
        <div class="clean-card">
          <p class="card-desc" style="margin:0;">
            ✨ All clear for this horizon! ${
              b.energy_mode === 'low_spoons' && h === '1m'
                ? '30-day items are gently hidden while you are in Low Spoons Mode.'
                : 'Future-You is completely caught up here.'
            }
          </p>
        </div>`;
    } else {
      suggList.innerHTML = suggestions
        .map((s) => {
          const steps = (s.micro_steps || []).map((st) => `<li>${this.escape(st)}</li>`).join('');
          const actionLabel = s.inline_action_label || `🚀 Launch & Auto-Complete (+${s.xp_reward} XP)`;
          return `
            <article class="clean-card">
              <div class="card-meta-row">
                <span class="source-tag">${this.escape(s.source_label)} • ${this.escape(s.due_context)}</span>
                <span class="xp-tag">+${s.xp_reward} XP</span>
              </div>
              <div>
                <button class="target-link-pill" onclick="App.launchAndCompleteSuggestion(${s.id}, ${Boolean(s.is_daily_boss)}, false)" title="Opens the linked file/target and pins a floating Done bar">
                  🔗 ${this.escape(s.target_label || 'Open Linked Target')} ↗
                </button>
              </div>
              <h4 class="card-title clickable-title" onclick="App.launchAndCompleteSuggestion(${s.id}, ${Boolean(s.is_daily_boss)}, true)" title="Click to launch target & auto-complete in 1 move">
                ${s.is_daily_boss ? '⚔️ ' : ''}${this.escape(s.title)} ↗
              </h4>
              <p class="card-desc">${this.escape(s.why_it_matters)}</p>
              <div class="micro-starter-callout">
                <strong>Zero-Friction Move:</strong> ${this.escape(s.starter_micro_step)}
              </div>
              ${steps ? `<ol class="micro-steps-list">${steps}</ol>` : ''}
              <div class="card-actions-row">
                <button class="btn-primary" onclick="App.launchAndCompleteSuggestion(${s.id}, ${Boolean(s.is_daily_boss)}, true)">
                  ${this.escape(actionLabel)}
                </button>
                <button class="btn-secondary" onclick="App.launchAndCompleteSuggestion(${s.id}, ${Boolean(s.is_daily_boss)}, false)">
                  ↗ Open Target &amp; Pin 'Done' Bar
                </button>
                <button class="btn-ghost" onclick="App.breakSuggestionSteps(${s.id})">
                  🔨 Shrink Steps
                </button>
              </div>
            </article>
          `;
        })
        .join('');
    }

    const events = (b.events_by_horizon && b.events_by_horizon[h]) || [];
    const evList = document.getElementById('horizon-events-list');
    if (events.length === 0) {
      evList.innerHTML = `<div class="clean-card"><p class="card-desc" style="margin:0;">No calendar events in this window.</p></div>`;
    } else {
      evList.innerHTML = events
        .map(
          (ev) => `
          <article class="clean-card">
            <div class="card-meta-row">
              <span class="source-tag">${this.escape(ev.account_label)} • ${this.escape(ev.location)}</span>
              <span class="xp-tag">Social ${ev.social_load}/10 • Cog ${ev.cognitive_load}/10</span>
            </div>
            <div>
              <button class="target-link-pill" onclick="App.openDirectTarget('${this.escapeAttr(ev.local_file_path)}', '${this.escapeAttr(ev.target_url)}', '${this.escapeAttr(ev.target_label)}')">
                ${this.escape(ev.target_label || '📅 Open Event & Prep Doc')} ↗
              </button>
            </div>
            <h4 class="card-title clickable-title" onclick="App.openDirectTarget('${this.escapeAttr(ev.local_file_path)}', '${this.escapeAttr(ev.target_url)}', '${this.escapeAttr(ev.title)}')">
              ${this.escape(ev.title)} ↗
            </h4>
            <p class="card-desc">🕒 ${this.escape(ev.start_time)} → ${this.escape(ev.end_time)}</p>
            <div class="micro-starter-callout">
              <strong>🛡️ Transition Buffer (${ev.transition_buffer_mins}m):</strong> ${this.escape(ev.prep_needed)}
            </div>
            <div class="card-actions-row">
              <button class="btn-secondary" onclick="App.openDirectTarget('${this.escapeAttr(ev.local_file_path)}', '${this.escapeAttr(ev.target_url)}', '${this.escapeAttr(ev.target_label)}')">
                📂 Open Meeting Doc / Join Link
              </button>
              <button class="btn-ghost" onclick="App.openDirectTarget('', '${this.escapeAttr(ev.target_url)}', 'Calendar')">
                📅 Open in Calendar ↗
              </button>
            </div>
          </article>`
        )
        .join('');
    }
  },

  async completeSuggestion(id, isBoss = false) {
    const res = await this.api('/api/suggestions/complete', 'POST', { id });
    if (res.ok) {
      this.playChime(isBoss);
      if (isBoss) this.burstConfetti();
      this.updateHUD(res.progress);
      await this.loadBriefing();
      await this.loadVault(this.state.selectedVaultWindow);
    }
  },

  async breakSuggestionSteps(id) {
    this.showToast('🧠 Breaking task into tiny 60-second AuDHD micro-steps...');
    const res = await this.api('/api/suggestions/micro-steps', 'POST', { id });
    if (res.ok) {
      await this.loadBriefing();
      this.showToast('✨ Micro-steps updated!');
    }
  },

  /* ------------------------------------------------------------------------
     VIEW 2: MULTI-INBOX EMAIL TRIAGE & PROACTIVE DRAFT STUDIO
     ------------------------------------------------------------------------ */
  async loadEmails() {
    const data = await this.api('/api/emails');
    this.state.emails = data.emails || [];
    document.getElementById('nav-email-count').textContent = this.state.emails.length;
    this.renderEmails();
  },

  renderEmails() {
    const container = document.getElementById('triage-email-list');
    if (this.state.emails.length === 0) {
      container.innerHTML = `
        <div class="clean-card">
          <h3 class="card-title">🎉 Inbox Triage Zero!</h3>
          <p class="card-desc" style="margin:0;">Every actionable email across your Gmail and Outlook accounts has been handled and logged in your Accomplishment Vault.</p>
        </div>`;
      return;
    }

    container.innerHTML = this.state.emails
      .map(
        (e) => `
        <article class="email-studio-card" id="email-card-${e.id}">
          <!-- Left: Low-Cognitive-Load Triage Brief + Direct File/Inbox Links -->
          <div>
            <div class="card-meta-row">
              <span class="urgency-pill ${e.urgency}">
                ${e.urgency === 'action_required' ? '🔴 Needs Reply Today' : '🟡 Quick Confirmation'}
              </span>
              <span class="source-tag">${this.escape(e.account_label)}</span>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:4px;">
              ${
                e.attachment_label
                  ? `<button class="target-link-pill" onclick="App.openDirectTarget('${this.escapeAttr(e.local_file_path)}', '${this.escapeAttr(e.target_url)}', '${this.escapeAttr(e.attachment_label)}')">
                       ${this.escape(e.attachment_label)} ↗
                     </button>`
                  : ''
              }
              <button class="target-link-pill" onclick="App.openDirectTarget('', '${this.escapeAttr(e.target_url)}', 'Original Thread')">
                📬 Open Thread in ${e.provider === 'google' ? 'Gmail' : 'Outlook'} ↗
              </button>
            </div>
            <h3 class="card-title clickable-title" onclick="App.openDirectTarget('${this.escapeAttr(e.local_file_path)}', '${this.escapeAttr(e.target_url)}', '${this.escapeAttr(e.subject)}')">
              ${this.escape(e.subject)} ↗
            </h3>
            <p class="source-tag" style="margin-bottom:10px;">From: <strong>${this.escape(e.sender_name)}</strong> (${this.escape(e.sender_email)}) • ${this.escape(e.received_at)}</p>

            <div class="micro-starter-callout">
              <strong>1-Sentence Summary:</strong><br/>
              ${this.escape(e.one_line_brief)}
            </div>
            <p class="card-desc"><strong>Suggested Action:</strong> ${this.escape(e.what_they_need)}</p>
          </div>

          <!-- Right: Proactive Editable Draft + 1-Click Tone Shifters & Direct Send -->
          <div>
            <div class="tone-bar">
              <span class="source-tag">Shift Tone:</span>
              <button class="chip-btn" onclick="App.shiftEmailTone(${e.id}, 'shorter')">⚡ Shorter</button>
              <button class="chip-btn" onclick="App.shiftEmailTone(${e.id}, 'warmer')">💛 Warmer</button>
              <button class="chip-btn" onclick="App.shiftEmailTone(${e.id}, 'polite_boundary')">🛡️ Polite Boundary / Next Week</button>
            </div>
            <textarea
              id="draft-box-${e.id}"
              class="textarea-clean"
              rows="6"
              style="margin-bottom:10px;"
            >${this.escape(e.draft_reply)}</textarea>
            <div class="card-actions-row">
              <button class="btn-primary" onclick="App.sendEmailDraft(${e.id}, 'send')">
                ✉️ Approve &amp; Send Here (+${e.xp_reward} XP)
              </button>
              <button class="btn-secondary" onclick="App.copyAndCompleteEmail(${e.id}, ${e.xp_reward})">
                📋 Copy Reply to Clipboard &amp; Complete (+${e.xp_reward} XP)
              </button>
              <button class="btn-ghost" onclick="App.sendEmailDraft(${e.id}, 'draft')">
                📥 Clear to Vault
              </button>
            </div>
          </div>
        </article>`
      )
      .join('');
  },

  async copyAndCompleteEmail(emailId, xpReward) {
    const box = document.getElementById(`draft-box-${emailId}`);
    const bodyText = box ? box.value : '';
    try {
      await navigator.clipboard.writeText(bodyText);
      this.showToast('📋 Reply copied to your clipboard! Just paste into Outlook/Gmail.');
    } catch (_) {}
    await this.sendEmailDraft(emailId, 'draft', bodyText);
  },

  async submitCustomEmailTriage(event) {
    event.preventDefault();
    const sender = document.getElementById('custom-email-sender').value.trim();
    const subject = document.getElementById('custom-email-subject').value.trim();
    const raw_email_text = document.getElementById('custom-email-body').value.trim();
    const btn = document.getElementById('custom-email-btn');
    if (!raw_email_text) return;

    btn.disabled = true;
    btn.textContent = '🧠 Summarizing & Drafting Reply in Your Voice...';
    const res = await this.api('/api/emails/triage-custom', 'POST', {
      sender_name: sender,
      subject,
      raw_email_text,
    });
    btn.disabled = false;
    btn.textContent = '⚡ Summarize & Draft Reply For Me';

    if (res.ok) {
      document.getElementById('custom-email-sender').value = '';
      document.getElementById('custom-email-subject').value = '';
      document.getElementById('custom-email-body').value = '';
      this.playChime(false);
      this.showToast('✨ Email triaged & reply drafted below!');
      await this.loadEmails();
    }
  },

  async shiftEmailTone(emailId, tone) {
    this.showToast(`✨ Shifting draft tone to "${tone.replace('_', ' ')}"...`);
    const res = await this.api('/api/emails/tone', 'POST', { id: emailId, tone });
    if (res.ok) {
      const box = document.getElementById(`draft-box-${emailId}`);
      if (box) box.value = res.draft_reply;
      this.showToast('✓ Draft updated! Feel free to tweak before sending.');
    }
  },

  async sendEmailDraft(emailId, action, overrideBody = null) {
    const box = document.getElementById(`draft-box-${emailId}`);
    const bodyText = overrideBody !== null ? overrideBody : (box ? box.value : '');
    const res = await this.api('/api/emails/send', 'POST', {
      id: emailId,
      draft_reply: bodyText,
      action,
    });
    if (res.ok) {
      this.playChime(false);
      this.updateHUD(res.progress);
      await this.loadEmails();
      await this.loadBriefing();
      await this.loadVault(this.state.selectedVaultWindow);
    }
  },

  /* ------------------------------------------------------------------------
     VIEW 3: SHINY OBJECT IDEA SANDBOX & AUTONOMOUS INCUBATOR
     ------------------------------------------------------------------------ */
  async loadIdeas() {
    const data = await this.api('/api/ideas');
    this.state.ideas = data.ideas || [];
    this.renderIdeas();
  },

  renderIdeas() {
    const container = document.getElementById('idea-dossier-list');
    if (this.state.ideas.length === 0) {
      container.innerHTML = `<div class="clean-card"><p class="card-desc">No ideas parked yet. Drop your next wild spark above!</p></div>`;
      return;
    }

    container.innerHTML = this.state.ideas
      .map((item) => {
        const d = item.dossier || {};
        const experiments = (d.micro_experiments || [])
          .map((ex) => `<li>${this.escape(ex)}</li>`)
          .join('');
        return `
          <article class="dossier-card">
            <div class="card-meta-row">
              <span class="source-tag">${this.escape(item.category)} • ${this.escape(item.effort_estimate)}</span>
              <span class="dossier-score-pill">Viability ${item.viability_score}/100</span>
            </div>
            <div>
              <button class="target-link-pill" onclick="App.openDirectTarget('', '${this.escapeAttr(item.notion_url || 'https://www.notion.so')}', 'Notion Idea Incubator')">
                📓 Open Dossier in Notion Incubator ↗
              </button>
            </div>
            <h4 class="card-title">💡 ${this.escape(item.title)}</h4>
            <p class="card-desc"><em>"${this.escape(item.raw_spark)}"</em></p>

            <div class="guardrail-box">
              <strong>🛡️ Priority Guardrail (${this.escape(item.distraction_risk)}):</strong><br/>
              ${this.escape(d.priority_guardrail || 'Parked safely so your today priorities stay protected.')}
            </div>

            <p class="card-desc"><strong>Autonomous Agent Thesis:</strong> ${this.escape(d.core_thesis || '')}</p>
            <p class="card-desc"><strong>Why It Excites Your Brain:</strong> ${this.escape(d.why_its_exciting || '')}</p>
            <p class="card-desc"><strong>Devil's Advocate Reality Check:</strong> ${this.escape(d.reality_check || '')}</p>

            ${
              experiments
                ? `<div style="margin-top:8px;">
                     <strong style="font-size:0.78rem; color:var(--text-muted);">NEXT 3 ZERO-COMMITMENT MICRO-EXPERIMENTS (FOR FREE TIME):</strong>
                     <ol class="micro-steps-list">${experiments}</ol>
                   </div>`
                : ''
            }
            <div class="source-tag" style="margin-top:8px;">🤖 ${this.escape(d.researched_by || 'Researched by Gemini + Claude Sandbox Agent')} • Synced to Notion Incubator</div>
          </article>
        `;
      })
      .join('');
  },

  async submitIdea(event) {
    event.preventDefault();
    const titleEl = document.getElementById('idea-title-input');
    const sparkEl = document.getElementById('idea-spark-input');
    const catEl = document.getElementById('idea-category-input');
    const btn = document.getElementById('idea-submit-btn');

    const title = titleEl.value.trim();
    const raw_spark = sparkEl.value.trim();
    const category = catEl.value;
    if (!title) return;

    btn.disabled = true;
    btn.textContent = '🤖 Parking Idea & Running AI Incubator Research...';

    const res = await this.api('/api/ideas', 'POST', { title, raw_spark, category });
    btn.disabled = false;
    btn.textContent = '🧪 Park Idea & Dispatch AI Agent (+25 XP)';

    if (res.ok) {
      titleEl.value = '';
      sparkEl.value = '';
      this.playChime(true);
      this.burstConfetti();
      this.updateHUD(res.progress);
      await this.loadIdeas();
      await this.loadVault(this.state.selectedVaultWindow);
    }
  },

  /* ------------------------------------------------------------------------
     VIEW 4: AuDHD COACH, BODY-DOUBLING TIMER & TASK BREAKER
     ------------------------------------------------------------------------ */
  async loadCoachMessages() {
    const data = await this.api('/api/coach');
    this.renderCoachMessages(data.messages || []);
  },

  renderCoachMessages(messages) {
    const box = document.getElementById('coach-messages-box');
    box.innerHTML = messages
      .map(
        (m) => `
        <div class="chat-bubble ${m.role === 'user' ? 'user' : 'coach'}">
          ${this.formatBold(m.content)}
        </div>`
      )
      .join('');
    box.scrollTop = box.scrollHeight;
  },

  async submitCoachMessage(event) {
    event.preventDefault();
    const input = document.getElementById('coach-input');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    await this.sendQuickCoach(msg);
  },

  async sendQuickCoach(message) {
    const res = await this.api('/api/coach', 'POST', { message });
    if (res.ok) {
      this.renderCoachMessages(res.messages || []);
    }
  },

  setTimerMinutes(mins) {
    this.resetTimer();
    this.state.timerSeconds = mins * 60;
    this.updateTimerDisplay();
  },

  updateTimerDisplay() {
    const m = String(Math.floor(this.state.timerSeconds / 60)).padStart(2, '0');
    const s = String(this.state.timerSeconds % 60).padStart(2, '0');
    document.getElementById('focus-timer-display').textContent = `${m}:${s}`;
  },

  toggleTimer() {
    const btn = document.getElementById('timer-start-btn');
    if (this.state.timerRunning) {
      clearInterval(this.state.timerInterval);
      this.state.timerRunning = false;
      btn.textContent = '▶ Resume Body-Doubling Sprint';
    } else {
      this.state.timerRunning = true;
      btn.textContent = '⏸ Pause Sprint';
      this.state.timerInterval = setInterval(async () => {
        if (this.state.timerSeconds > 0) {
          this.state.timerSeconds--;
          this.updateTimerDisplay();
        } else {
          clearInterval(this.state.timerInterval);
          this.state.timerRunning = false;
          btn.textContent = '▶ Start Body-Doubling Sprint (+30 XP)';
          this.playChime(true);
          this.burstConfetti();
          const claim = await this.api('/api/roulette/claim-instant', 'POST', {
            xp: 30,
            reason: '⏱️ Completed Body-Doubling Focus Sprint!',
          });
          this.updateHUD(claim.progress);
        }
      }, 1000);
    }
  },

  resetTimer() {
    if (this.state.timerInterval) clearInterval(this.state.timerInterval);
    this.state.timerRunning = false;
    this.state.timerSeconds = 15 * 60;
    this.updateTimerDisplay();
    const btn = document.getElementById('timer-start-btn');
    if (btn) btn.textContent = '▶ Start Body-Doubling Sprint (+30 XP)';
  },

  async breakDownCustomTask(event) {
    event.preventDefault();
    const input = document.getElementById('custom-task-input');
    const title = input.value.trim();
    if (!title) return;
    this.showToast('🔨 Shrinking task into 60-second starter steps...');
    const res = await this.api('/api/tasks/break-down', 'POST', { title });
    if (res.ok) {
      const list = document.getElementById('custom-micro-steps-list');
      list.innerHTML = (res.micro_steps || []).map((s) => `<li>${this.escape(s)}</li>`).join('');
    }
  },

  /* ------------------------------------------------------------------------
     VIEW 5: ACCOMPLISHMENT & CLEARED VAULT (DAY / WEEK / MONTH / YEAR)
     ------------------------------------------------------------------------ */
  async loadVault(windowKey = 'week') {
    this.state.selectedVaultWindow = windowKey;
    document.querySelectorAll('[data-vault-window]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.vaultWindow === windowKey);
    });

    const data = await this.api(`/api/vault?window=${windowKey}`);
    this.state.vault = data;

    if (data.counts_by_window) {
      ['day', 'week', 'month', 'year'].forEach((w) => {
        const el = document.getElementById(`v-count-${w}`);
        if (el) el.textContent = data.counts_by_window[w] || 0;
      });
      document.getElementById('nav-vault-count').textContent = data.counts_by_window.year || data.total_items;
    }

    document.getElementById('vault-celebration-summary').innerHTML = this.formatBold(data.coach_celebration_summary || '');
    document.getElementById('vault-kpi-xp').textContent = data.total_xp_earned || 0;
    document.getElementById('vault-kpi-bosses').textContent = data.bosses_slain || 0;
    document.getElementById('vault-kpi-emails').textContent = data.emails_cleared || 0;
    document.getElementById('vault-kpi-ideas').textContent = data.ideas_parked || 0;

    const listEl = document.getElementById('vault-items-list');
    const items = data.items || [];
    if (items.length === 0) {
      listEl.innerHTML = `<div class="clean-card"><p class="card-desc">No cleared items in this time window yet.</p></div>`;
    } else {
      listEl.innerHTML = items
        .map((it) => {
          const icon = {
            boss_defeated: '⚔️',
            email_sent: '✉️',
            idea_parked: '🛡️',
            horizon_prep: '🌅',
            notion_task: '📓',
          }[it.item_type] || '✓';
          const hasTarget = Boolean(it.local_file_path || it.target_url);
          return `
            <article class="clean-card">
              <div class="card-meta-row">
                <span class="source-tag">${this.escape(it.account_label)} • ${this.escape(it.cleared_at.slice(0, 16).replace('T', ' '))}</span>
                <span class="xp-tag">+${it.xp_earned} XP ${it.was_boss ? '• 🏆 BOSS' : ''}</span>
              </div>
              ${
                hasTarget
                  ? `<div>
                       <button class="target-link-pill" onclick="App.openDirectTarget('${this.escapeAttr(it.local_file_path)}', '${this.escapeAttr(it.target_url)}', '${this.escapeAttr(it.target_label || it.title)}')">
                         ${this.escape(it.target_label || '📂 Re-Open Linked File / Task')} ↗
                       </button>
                     </div>`
                  : ''
              }
              <h4 class="card-title ${hasTarget ? 'clickable-title' : ''}" ${
                hasTarget
                  ? `onclick="App.openDirectTarget('${this.escapeAttr(it.local_file_path)}', '${this.escapeAttr(it.target_url)}', '${this.escapeAttr(it.title)}')"`
                  : ''
              }>
                ${icon} ${this.escape(it.title)} ${hasTarget ? '↗' : ''}
              </h4>
              <p class="card-desc" style="margin:0;">${this.escape(it.summary || '')}</p>
            </article>
          `;
        })
        .join('');
    }
  },

  async syncVaultToNotion() {
    this.showToast('📓 Syncing Daily Briefing, Idea Incubator & Accomplishment Vault to Notion...');
    const res = await this.api('/api/vault/sync-notion', 'POST');
    if (res.ok) {
      this.playChime(false);
      this.showToast(`✓ Synced across ${(res.workspaces_synced || []).length} Notion Workspaces!`);
    }
  },

  /* ------------------------------------------------------------------------
     MULTI-ACCOUNT MODAL & AI KEYS
     ------------------------------------------------------------------------ */
  async openAccountsModal() {
    document.getElementById('accounts-modal').classList.remove('hidden');
    const data = await this.api('/api/accounts');
    const list = document.getElementById('modal-accounts-list');
    list.innerHTML = (data.accounts || [])
      .map(
        (a) => `
        <div class="modal-acc-item">
          <div>
            <span class="account-dot" style="background:${a.color_tag}; display:inline-block; margin-right:6px;"></span>
            <strong>${this.escape(a.account_label)}</strong> (${this.escape(a.provider.toUpperCase())})
            <div class="source-tag">${this.escape(a.account_identifier)}</div>
          </div>
          <button class="chip-btn" onclick="App.openDirectTarget('', '${this.escapeAttr(a.portal_url || 'https://www.notion.so')}', '${this.escapeAttr(a.account_label)}')">
            Open Workspace ↗
          </button>
        </div>`
      )
      .join('');
  },

  closeAccountsModal() {
    document.getElementById('accounts-modal').classList.add('hidden');
  },

  async addAccount(event) {
    event.preventDefault();
    const provider = document.getElementById('acc-provider').value;
    const account_label = document.getElementById('acc-label').value.trim();
    const account_identifier = document.getElementById('acc-identifier').value.trim();
    const api_token = document.getElementById('acc-token').value.trim();
    const ics_url = (document.getElementById('acc-ics') || {}).value?.trim() || '';
    const app_password = (document.getElementById('acc-app-pass') || {}).value?.trim() || '';
    const res = await this.api('/api/accounts', 'POST', {
      provider,
      account_label,
      account_identifier,
      api_token,
      ics_url,
      app_password,
    });
    if (res.ok) {
      document.getElementById('acc-label').value = '';
      document.getElementById('acc-identifier').value = '';
      document.getElementById('acc-token').value = '';
      if (document.getElementById('acc-ics')) document.getElementById('acc-ics').value = '';
      if (document.getElementById('acc-app-pass')) document.getElementById('acc-app-pass').value = '';
      this.showToast(`✓ Linked ${account_label}! Running live sync...`);
      await this.triggerLiveSync(false);
      await this.openAccountsModal();
    }
  },

  async triggerLiveSync(clearDemoData = false) {
    this.showToast('🔄 Pulling live events, unread emails & Notion pages...');
    const res = await this.api('/api/sync/live', 'POST', {
      clear_demo_data: clearDemoData,
    });
    if (res.ok) {
      this.showToast(
        `✓ Live Sync Complete: ${res.events_synced} events, ${res.emails_triaged} emails triaged, ${res.notion_items_synced} Notion items!`
      );
      await this.loadBriefing();
      await this.loadEmails();
    }
  },

  async saveAIKeys(event) {
    event.preventDefault();
    const gemini_api_key = document.getElementById('key-gemini').value.trim();
    const anthropic_api_key = document.getElementById('key-claude').value.trim();
    const res = await this.api('/api/settings/keys', 'POST', {
      gemini_api_key,
      anthropic_api_key,
    });
    if (res.ok) {
      this.showToast('✓ Dual AI Engine keys (Gemini + Claude) saved!');
      document.getElementById('key-gemini').value = '';
      document.getElementById('key-claude').value = '';
    }
  },

  /* ------------------------------------------------------------------------
     HELPERS
     ------------------------------------------------------------------------ */
  escape(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },

  escapeAttr(str) {
    return String(str || '')
      .replace(/\\/g, '\\\\')
      .replace(/'/g, "\\'")
      .replace(/"/g, '&quot;');
  },

  formatBold(str) {
    return this.escape(str).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  },
};

window.addEventListener('DOMContentLoaded', () => App.init());
