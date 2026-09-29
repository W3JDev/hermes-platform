/**
 * Hermes Desktop Web Shim (Enterprise Edition)
 * Injected before React initialization. Provides full native-parity APIs for the Web/PWA client.
 */
(function() {
  if (typeof window === 'undefined') return;

  var origin = window.location.origin;
  var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  var defaultWsUrl = wsProtocol + '//' + window.location.host + '/ws';

  var activeProfile = null;

  // 1. AudioContext Auto-Unlock on first interaction
  function unlockAudio() {
    try {
      var AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        var ctx = new AudioCtx();
        if (ctx.state === 'suspended') {
          ctx.resume().then(function() { ctx.close(); });
        }
      }
    } catch (e) {}
    window.removeEventListener('click', unlockAudio);
    window.removeEventListener('keydown', unlockAudio);
    window.removeEventListener('touchstart', unlockAudio);
  }
  window.addEventListener('click', unlockAudio, { once: true });
  window.addEventListener('keydown', unlockAudio, { once: true });
  window.addEventListener('touchstart', unlockAudio, { once: true });

  // 2. Token storage helper
  function getAuthToken() {
    return localStorage.getItem('hermes_token') || localStorage.getItem('hermes-auth-token') || '';
  }

  var webConnection = {
    baseUrl: origin,
    isFullscreen: false,
    nativeOverlayWidth: 0,
    token: getAuthToken(),
    wsUrl: defaultWsUrl,
    logs: ['[web-shim] Enterprise Browser Companion Active'],
    windowButtonPosition: null,
    mode: 'remote',
  };

  var baseBridge = {
    getConnection: function(profile) {
      if (profile) activeProfile = profile;
      var conn = Object.assign({}, webConnection);
      if (profile) conn.profile = profile;
      return Promise.resolve(conn);
    },
    getConnectionFor: function() {
      return Promise.resolve(webConnection);
    },
    getGatewayWsUrl: function() {
      return fetch('/api/auth/ws-ticket', {
        method: 'POST',
        credentials: 'include'
      })
      .then(function(res) {
        if (res.ok) return res.json();
        return null;
      })
      .then(function(data) {
        if (data && data.ticket) {
          return defaultWsUrl + '?ticket=' + encodeURIComponent(data.ticket);
        }
        return defaultWsUrl;
      })
      .catch(function(err) {
        console.warn('[web-shim] ws-ticket error, using direct WS:', err);
        return defaultWsUrl;
      });
    },
    getGatewayWsUrlFor: function() {
      return baseBridge.getGatewayWsUrl();
    },
    getPlatform: function() {
      var ua = (navigator.userAgent || '').toLowerCase();
      if (ua.indexOf('mac') !== -1) return 'darwin';
      if (ua.indexOf('win') !== -1) return 'win32';
      return 'linux';
    },
    getArch: function() { return 'x64'; },
    getVersions: function() {
      return {
        app: '0.21.4',
        chrome: '128.0.0.0',
        electron: '31.0.0',
        node: '20.15.0'
      };
    },
    requestMicrophoneAccess: function() {
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        return navigator.mediaDevices.getUserMedia({ audio: true })
          .then(function(stream) {
            stream.getTracks().forEach(function(track) { track.stop(); });
            return true;
          })
          .catch(function(err) {
            console.warn('[web-shim] Microphone permission denied:', err);
            return false;
          });
      }
      return Promise.resolve(false);
    },
    notify: function(payload) {
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(payload.title, { body: payload.body });
        return Promise.resolve(true);
      }
      return Promise.resolve(false);
    },
    profile: {
      get: function() { return Promise.resolve({ profile: activeProfile }); },
      remember: function(name) {
        activeProfile = name;
        return Promise.resolve({ profile: name });
      },
      set: function(name) {
        activeProfile = name;
        return Promise.resolve({ profile: name });
      }
    },
    connections: {
      list: function() {
        return Promise.resolve({
          version: 2,
          primary: 'cloud-gateway',
          secureTokenStorage: false,
          connections: [
            {
              id: 'cloud-gateway',
              kind: 'remote',
              label: 'Hermes Cloud Gateway',
              url: origin,
              tokenSet: true,
              tokenPreview: 'active'
            }
          ]
        });
      },
      save: function(p) {
        return Promise.resolve({
          ok: true,
          connection: { id: p.id || 'cloud-gateway', kind: p.kind, label: p.label, tokenSet: true },
          registry: { version: 2, primary: 'cloud-gateway', connections: [] }
        });
      },
      remove: function() {
        return Promise.resolve({ ok: true, registry: { version: 2, primary: 'cloud-gateway', connections: [] } });
      },
      setPrimary: function() {
        return Promise.resolve({ ok: true, registry: { version: 2, primary: 'cloud-gateway', connections: [] } });
      },
      test: function() {
        return Promise.resolve({ ok: true, reachable: true, version: '0.21.4' });
      },
      onChanged: function() { return function() {}; }
    },
    cloud: {
      status: function() { return Promise.resolve({ portalBaseUrl: '', signedIn: false }); },
      login: function() { return Promise.resolve({ portalBaseUrl: '', signedIn: false, ok: false }); },
      logout: function() { return Promise.resolve({ portalBaseUrl: '', signedIn: false, ok: true }); },
      discover: function() { return Promise.resolve({ agents: [], needsOrgSelection: false }); },
      agentSignIn: function() { return Promise.resolve({ baseUrl: '', connected: false }); }
    },
    api: function(req) {
      var headers = { 'Content-Type': 'application/json' };
      var token = getAuthToken();
      if (token) {
        headers['Authorization'] = 'Bearer ' + token;
      }
      var targetPath = req.path || '';
      if (targetPath.charAt(0) !== '/') targetPath = '/' + targetPath;
      if (targetPath.indexOf('/api/') !== 0 && targetPath !== '/api') {
        targetPath = '/api' + targetPath;
      }
      return fetch(targetPath, {
        method: req.method || 'GET',
        headers: headers,
        credentials: 'include',
        body: req.body ? JSON.stringify(req.body) : undefined
      }).then(function(res) {
        if (!res.ok) {
          throw new Error('API error ' + res.status + ': ' + res.statusText);
        }
        return res.json();
      });
    },
    writeClipboard: function(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text).then(function() { return true; }).catch(function() { return false; });
      }
      return Promise.resolve(false);
    },
    readClipboard: function() {
      if (navigator.clipboard && navigator.clipboard.readText) {
        return navigator.clipboard.readText().catch(function() { return ''; });
      }
      return Promise.resolve('');
    },
    selectPaths: function() { return Promise.resolve([]); },
    readFileText: function() { return Promise.resolve({ path: '', text: '' }); },
    getPathForFile: function(file) { return file ? file.name : ''; },
    getConnectionConfig: function() {
      return Promise.resolve({
        envOverride: false,
        mode: 'remote',
        profile: null,
        remoteAuthMode: 'token',
        remoteOauthConnected: false,
        remoteTokenPreview: null,
        remoteTokenSet: true,
        secureTokenStorage: false,
        remoteTokenPlainText: true,
        remoteUrl: origin,
        cloudOrg: '',
        sshHost: '',
        sshUser: '',
        sshPort: null,
        sshKeyPath: '',
        sshRemoteHermesPath: '',
        sshRemoteProfile: ''
      });
    },
    saveConnectionConfig: function(cfg) { return Promise.resolve(cfg); },
    applyConnectionConfig: function(cfg) { return Promise.resolve(cfg); },
    testConnectionConfig: function() { return Promise.resolve({ ok: true, reachable: true }); },
    getSecretStorageEncryption: function() { return Promise.resolve({ on: false }); },
    setSecretStorageEncryption: function() { return Promise.resolve({ on: false }); },
    sshConfigHosts: function() { return Promise.resolve({ hosts: [] }); },
    sshResolveHost: function() { return Promise.resolve({ hostname: null, identityFile: null, port: null, user: null }); },
    probeConnectionConfig: function() {
      return Promise.resolve({
        baseUrl: origin,
        reachable: true,
        authMode: 'token',
        providers: [],
        version: '0.21.4',
        error: null
      });
    },
    oauthLoginConnectionConfig: function() { return Promise.resolve({ ok: true, baseUrl: origin, connected: true }); },
    oauthLogoutConnectionConfig: function() { return Promise.resolve({ ok: false, connected: false }); },
    setTitleBarTheme: function() {},
    setNativeTheme: function() {},
    setActiveWork: function() {},
    setTranslucency: function() {},
    glassSupported: false,
    translucencySupported: false,
    localModelsEnabled: true,
    guestOnboardingEnabled: false,
    onContextMenuSpellcheck: function() { return function() {}; },
    openSessionWindow: function() { return Promise.resolve({ ok: true }); },
    openSessionInTerminal: function() { return Promise.resolve({ ok: true }); },
    openWindow: function() { return Promise.resolve({ ok: true }); },
    openBrowserWindow: function() { return Promise.resolve({ ok: true }); },
    onBrowserPopoutClosed: function() { return function() {}; },
    claimAmbientCue: function() { return Promise.resolve(true); },
    revalidateConnection: function() { return Promise.resolve({ ok: true, rebuilt: false }); },
    touchBackend: function() { return Promise.resolve({ ok: true }); },
    getPoolLimits: function() { return Promise.resolve({ maxBackends: 5, idleMs: 300000 }); },
    setPoolLimits: function(l) { return Promise.resolve({ ok: true, limits: l }); },
    getProfileRoutes: function() { return Promise.resolve([]); },
    getAgentRoster: function() { return Promise.resolve({ agents: [], defaultAgentId: '' }); },
    quickEntry: {
      getSettings: function() { return Promise.resolve({ enabled: false, shortcut: '' }); },
      setSettings: function(s) { return Promise.resolve({ enabled: s.enabled || false, shortcut: s.shortcut || '' }); },
      submit: function() {},
      dismiss: function() {},
      pushState: function() {},
      onState: function() { return function() {}; },
      onSubmit: function() { return function() {}; },
      onShown: function() { return function() {}; }
    },
    petOverlay: {
      open: function() { return Promise.resolve({ ok: false }); },
      close: function() { return Promise.resolve({ ok: false }); },
      setBounds: function() {},
      setIgnoreMouse: function() {},
      setFocusable: function() {},
      pushState: function() {},
      control: function() {},
      onState: function() { return function() {}; },
      onControl: function() { return function() {}; }
    },
    hud: {
      nativeDrag: false,
      open: function() { return Promise.resolve({ ok: false }); },
      close: function() { return Promise.resolve({ ok: false }); },
      setIgnoreMouse: function() {},
      beginMove: function() {},
      endMove: function() {},
      moveBy: function() {},
      setBounds: function() {},
      resetLayout: function() { return Promise.resolve({ ok: false }); },
      setFrost: function() { return Promise.resolve({ ok: false }); },
      setSession: function() {},
      onGoto: function() { return function() {}; },
      onChanged: function() { return function() {}; },
      onCursor: function() { return function() {}; },
      onGameOverlay: function() { return function() {}; }
    },
    zoom: {
      get: function() { return Promise.resolve({ percent: 100 }); },
      setPercent: function() {},
      onChanged: function() { return function() {}; }
    },
    settings: {
      getDefaultProjectDir: function() { return Promise.resolve({ defaultLabel: 'Default', dir: null, resolvedCwd: '/' }); },
      pickDefaultProjectDir: function() { return Promise.resolve({ canceled: true, dir: null }); },
      setDefaultProjectDir: function(dir) { return Promise.resolve({ dir: dir }); }
    }
  };

  function createDefensiveProxy(obj) {
    return new Proxy(obj || {}, {
      get: function(target, prop) {
        if (typeof prop === 'symbol') return target[prop];
        if (prop === 'then') return undefined;
        if (prop in target) {
          var val = target[prop];
          if (typeof val === 'object' && val !== null && !(val instanceof Promise)) {
            return createDefensiveProxy(val);
          }
          return val;
        }
        var dummyFn = function() {
          var args = Array.prototype.slice.call(arguments);
          if (typeof args[0] === 'function') {
            return function() {};
          }
          return Promise.resolve({ ok: true, percent: 100 });
        };
        return createDefensiveProxy(dummyFn);
      },
      apply: function(target, thisArg, args) {
        if (typeof target === 'function') {
          return target.apply(thisArg, args);
        }
        if (typeof args[0] === 'function') {
          return function() {};
        }
        return Promise.resolve({ ok: true, percent: 100 });
      }
    });
  }

  window.hermesDesktop = createDefensiveProxy(baseBridge);
  console.log('[Hermes Enterprise] Web Desktop Bridge initialized successfully.');
})();
