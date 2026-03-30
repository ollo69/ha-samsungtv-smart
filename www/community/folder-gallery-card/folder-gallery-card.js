/**
 * Folder Gallery Card for Home Assistant
 * 
 * A custom Lovelace card that displays images from a folder
 * and triggers actions when clicked.
 * 
 * Installation:
 * 1. Copy this file to /config/www/community/folder-gallery-card/folder-gallery-card.js
 * 2. Add to Lovelace resources:
 *    url: /local/community/folder-gallery-card/folder-gallery-card.js
 *    type: module
 * 
 * Usage Example:
 * type: custom:folder-gallery-card
 * title: My Art Gallery
 * folder: /local/frame_art/personal
 * columns: 4
 * image_height: 150px
 * action:
 *   service: media_player.play_media
 *   target:
 *     entity_id: media_player.samsung_frame_tv
 *   data:
 *     media_content_type: image
 *     media_content_id: "{{image_path}}"
 */

class FolderGalleryCard extends HTMLElement {
  
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._images = [];
    this._config = {};
  }

  static get properties() {
    return {
      hass: {},
      config: {}
    };
  }

  setConfig(config) {
    if (!config.folder) {
      throw new Error('You need to define a folder');
    }
    
    this._config = {
      title: config.title || '',
      folder: config.folder,
      columns: config.columns || 4,
      image_height: config.image_height || '150px',
      aspect_ratio: config.aspect_ratio || null, // e.g., "1" for square, "16/9" for landscape, "3/4" for portrait
      gap: config.gap || '8px',
      border_radius: config.border_radius || '8px',
      show_filename: config.show_filename !== false,
      filter: config.filter || '*',
      action: config.action || null,
      tap_action: config.tap_action || null,
      hold_action: config.hold_action || null,
      sensor: config.sensor || null, // Sensor that provides image list
      image_list: config.image_list || null, // Static list of images
      ...config
    };
    
    this.render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;
    
    // Anti-flicker: Only update if folder_sensor state actually changed
    if (this._config.folder_sensor && oldHass) {
      const oldState = oldHass.states[this._config.folder_sensor];
      const newState = hass.states[this._config.folder_sensor];
      
      // Compare file_list attribute to detect real changes
      const oldFiles = oldState?.attributes?.file_list;
      const newFiles = newState?.attributes?.file_list;
      
      // Skip re-render if file_list is unchanged (prevents flickering)
      if (JSON.stringify(oldFiles) === JSON.stringify(newFiles)) {
        return; // No changes detected, skip expensive re-render
      }
      
      console.log('[FolderGallery] file_list changed, updating gallery');
    }
    
    this.updateImages();
  }

  get hass() {
    return this._hass;
  }

  updateImages() {
    if (!this._hass) return;
    
    let images = [];
    
    // Priority 1: folder_sensor (platform: folder)
    if (this._config.folder_sensor) {
      const folderState = this._hass.states[this._config.folder_sensor];
      if (folderState && folderState.attributes) {
        let fileList = folderState.attributes.file_list;
        
        console.log('[FolderGallery] folder_sensor file_list:', fileList, 'type:', typeof fileList, 'isArray:', Array.isArray(fileList));
        
        // Ensure folder path doesn't have trailing slash
        const folder = (this._config.folder || '').replace(/\/+$/, '');
        
        // Convert to array if needed
        if (typeof fileList === 'string') {
          fileList = fileList.split(',').map(f => f.trim()).filter(f => f);
        }
        
        if (Array.isArray(fileList) && fileList.length > 0) {
          this._images = fileList.map(f => {
            // f = "/config/www/frame_art/store/SAM-S100808.jpg"
            // On veut juste "SAM-S100808.jpg"
            const fullPath = String(f);
            const filename = fullPath.match(/[^\/]+$/)?.[0] || fullPath;
            const content_id = filename.replace(/\.[^/.]+$/, '');
            
            console.log('[FolderGallery] Processing:', fullPath, '→', filename);
            
            return {
              path: `${folder}/${filename}`,
              filename: filename,
              name: content_id,
              content_id: content_id
            };
          });
          
          console.log('[FolderGallery] Processed images:', this._images.slice(0, 2));
          this.renderGallery();
          return;
        }
      }
    }
    
    // Priority 2: sensor with images/file_list/thumbnails attribute
    if (this._config.sensor) {
      const sensorState = this._hass.states[this._config.sensor];
      if (sensorState && sensorState.attributes) {
        images = sensorState.attributes.images || 
                 sensorState.attributes.thumbnails ||
                 sensorState.attributes.items ||
                 [];
      }
    }
    
    // Priority 3: static image_list in config
    if (this._config.image_list && this._config.image_list.length > 0) {
      images = this._config.image_list;
    }

    // Normalize image format for methods 2 & 3
    const folder = (this._config.folder || '').replace(/\/+$/, '');
    
    this._images = images.map(img => {
      if (typeof img === 'string') {
        const parts = img.split('/');
        const filename = parts[parts.length - 1];
        const content_id = filename.replace(/\.[^/.]+$/, '');
        return {
          path: img.startsWith('/local') ? img : `${folder}/${filename}`,
          filename: filename,
          name: content_id,
          content_id: content_id
        };
      }
      return {
        path: img.path || img.url || img.thumbnail || '',
        filename: img.filename || img.name || 'unknown',
        name: img.name || img.title || img.filename?.replace(/\.[^/.]+$/, '').replace(/_/g, ' ') || 'Unknown',
        content_id: img.content_id || img.id || null,
        ...img
      };
    });

    this.renderGallery();
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        
        ha-card {
          padding: 16px;
          overflow: hidden;
        }
        
        .card-header {
          font-size: 1.2em;
          font-weight: 500;
          padding-bottom: 12px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        
        .image-count {
          font-size: 0.8em;
          opacity: 0.7;
          font-weight: normal;
        }
        
        .gallery-grid {
          display: grid;
          grid-template-columns: repeat(${this._config.columns}, 1fr);
          gap: ${this._config.gap};
        }
        
        .gallery-item {
          position: relative;
          cursor: pointer;
          border-radius: ${this._config.border_radius};
          overflow: hidden;
          background: var(--card-background-color, #1c1c1c);
          transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        
        .gallery-item:hover {
          transform: scale(1.03);
          box-shadow: 0 4px 20px rgba(0,0,0,0.3);
          z-index: 1;
        }
        
        .gallery-item:active {
          transform: scale(0.98);
        }
        
        .gallery-item img {
          width: 100%;
          ${this._config.aspect_ratio 
            ? `aspect-ratio: ${this._config.aspect_ratio};` 
            : `height: ${this._config.image_height};`}
          object-fit: cover;
          display: block;
          transition: opacity 0.3s ease;
        }
        
        .gallery-item img.loading {
          opacity: 0.5;
        }
        
        .gallery-item img.error {
          opacity: 0.3;
        }
        
        .image-overlay {
          position: absolute;
          bottom: 0;
          left: 0;
          right: 0;
          background: linear-gradient(transparent, rgba(0,0,0,0.8));
          padding: 8px;
          opacity: 0;
          transition: opacity 0.2s ease;
        }
        
        .gallery-item:hover .image-overlay {
          opacity: 1;
        }
        
        .image-name {
          color: white;
          font-size: 0.75em;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        
        .selected {
          outline: 3px solid var(--primary-color, #03a9f4);
          outline-offset: 2px;
        }
        
        .empty-state {
          text-align: center;
          padding: 40px 20px;
          opacity: 0.6;
        }
        
        .empty-state ha-icon {
          --mdc-icon-size: 48px;
          margin-bottom: 12px;
        }
        
        .loading-spinner {
          display: flex;
          justify-content: center;
          padding: 40px;
        }
        
        /* Responsive */
        @media (max-width: 600px) {
          .gallery-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        
        /* Lightbox */
        .lightbox {
          display: none;
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0,0,0,0.95);
          z-index: 999;
          justify-content: center;
          align-items: center;
          flex-direction: column;
        }
        
        .lightbox.open {
          display: flex;
        }
        
        .lightbox img {
          max-width: 90vw;
          max-height: 80vh;
          object-fit: contain;
          border-radius: 8px;
        }
        
        .lightbox-close {
          position: absolute;
          top: 20px;
          right: 20px;
          color: white;
          cursor: pointer;
          font-size: 2em;
          opacity: 0.7;
          transition: opacity 0.2s;
        }
        
        .lightbox-close:hover {
          opacity: 1;
        }
        
        .lightbox-actions {
          margin-top: 20px;
          display: flex;
          gap: 12px;
        }
        
        .lightbox-btn {
          background: var(--primary-color, #03a9f4);
          color: white;
          border: none;
          padding: 12px 24px;
          border-radius: 8px;
          cursor: pointer;
          font-size: 1em;
          transition: background 0.2s;
        }
        
        .lightbox-btn:hover {
          background: var(--primary-color-light, #29b6f6);
        }
        
        .lightbox-btn.secondary {
          background: rgba(255,255,255,0.1);
        }
      </style>
      
      <ha-card>
        ${this._config.title ? `
          <div class="card-header">
            <span>${this._config.title}</span>
            <span class="image-count"></span>
          </div>
        ` : ''}
        <div class="gallery-container">
          <div class="loading-spinner">
            <ha-circular-progress indeterminate></ha-circular-progress>
          </div>
        </div>
        
        <div class="lightbox" id="lightbox">
          <span class="lightbox-close" id="lightbox-close">&times;</span>
          <img id="lightbox-img" src="" alt="">
          <div class="lightbox-actions">
            <button class="lightbox-btn" id="lightbox-action">Select</button>
            <button class="lightbox-btn secondary" id="lightbox-close-btn">Close</button>
          </div>
        </div>
      </ha-card>
    `;

    // Setup lightbox events
    this.setupLightbox();
  }

  renderGallery() {
    const container = this.shadowRoot.querySelector('.gallery-container');
    const countEl = this.shadowRoot.querySelector('.image-count');
    
    if (!container) return;
    
    if (countEl) {
      countEl.textContent = `${this._images.length} images`;
    }

    if (this._images.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <ha-icon icon="mdi:image-off"></ha-icon>
          <div>No images found</div>
          <div style="font-size: 0.8em; margin-top: 8px;">
            Configure a sensor or image_list
          </div>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="gallery-grid">
        ${this._images.map((img, index) => `
          <div class="gallery-item" data-index="${index}" data-path="${img.path}" data-content-id="${img.content_id || ''}">
            <img src="${img.path}" alt="${img.name}" loading="lazy" class="loading"
                 onerror="this.classList.add('error')" 
                 onload="this.classList.remove('loading')">
            ${this._config.show_filename ? `
              <div class="image-overlay">
                <div class="image-name">${img.name}</div>
              </div>
            ` : ''}
          </div>
        `).join('')}
      </div>
    `;

    // Add click handlers
    container.querySelectorAll('.gallery-item').forEach(item => {
      item.addEventListener('click', (e) => this.handleClick(e, item));
      item.addEventListener('contextmenu', (e) => this.handleHold(e, item));
    });
  }

  setupLightbox() {
    const lightbox = this.shadowRoot.getElementById('lightbox');
    const closeBtn = this.shadowRoot.getElementById('lightbox-close');
    const closeBtnAlt = this.shadowRoot.getElementById('lightbox-close-btn');
    const actionBtn = this.shadowRoot.getElementById('lightbox-action');

    if (closeBtn) {
      closeBtn.addEventListener('click', () => this.closeLightbox());
    }
    if (closeBtnAlt) {
      closeBtnAlt.addEventListener('click', () => this.closeLightbox());
    }
    if (lightbox) {
      lightbox.addEventListener('click', (e) => {
        if (e.target === lightbox) this.closeLightbox();
      });
    }
    if (actionBtn) {
      actionBtn.addEventListener('click', () => {
        if (this._selectedImage) {
          this.executeAction(this._selectedImage);
          this.closeLightbox();
        }
      });
    }
  }

  openLightbox(imageData) {
    const lightbox = this.shadowRoot.getElementById('lightbox');
    const img = this.shadowRoot.getElementById('lightbox-img');
    const actionBtn = this.shadowRoot.getElementById('lightbox-action');
    
    if (lightbox && img) {
      this._selectedImage = imageData;
      img.src = imageData.path;
      lightbox.classList.add('open');
      
      // Update action button text
      if (actionBtn && this._config.action) {
        const actionName = this._config.action.service?.split('.').pop() || 'Select';
        actionBtn.textContent = actionName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
      }
    }
  }

  closeLightbox() {
    const lightbox = this.shadowRoot.getElementById('lightbox');
    if (lightbox) {
      lightbox.classList.remove('open');
      this._selectedImage = null;
    }
  }

  handleClick(e, item) {
    const index = parseInt(item.dataset.index);
    const imageData = this._images[index];
    
    // If tap_action is 'lightbox' or not defined with action, show lightbox
    if (this._config.tap_action === 'lightbox' || 
        (!this._config.tap_action && this._config.action)) {
      this.openLightbox(imageData);
    } 
    // Direct action on tap
    else if (this._config.tap_action === 'action' || this._config.action) {
      this.executeAction(imageData);
    }
    // More info
    else if (this._config.tap_action === 'more-info' && this._config.entity) {
      this.fireEvent('hass-more-info', { entityId: this._config.entity });
    }
  }

  handleHold(e, item) {
    e.preventDefault();
    const index = parseInt(item.dataset.index);
    const imageData = this._images[index];
    
    if (this._config.hold_action) {
      this.executeAction(imageData, this._config.hold_action);
    } else {
      this.openLightbox(imageData);
    }
  }

  executeAction(imageData, actionConfig = null) {
    const action = actionConfig || this._config.action;
    if (!action || !this._hass) return;

    const service = action.service;
    if (!service) return;

    const [domain, serviceName] = service.split('.');
    
    // Build service data with template substitution
    let serviceData = { ...(action.data || {}) };
    
    // Replace templates
    const replaceTemplates = (obj) => {
      if (typeof obj === 'string') {
        return obj
          .replace(/\{\{image_path\}\}/g, imageData.path)
          .replace(/\{\{filename\}\}/g, imageData.filename)
          .replace(/\{\{name\}\}/g, imageData.name)
          .replace(/\{\{content_id\}\}/g, imageData.content_id || '')
          .replace(/\{\{index\}\}/g, imageData.index || '');
      }
      if (typeof obj === 'object' && obj !== null) {
        const result = Array.isArray(obj) ? [] : {};
        for (const key in obj) {
          result[key] = replaceTemplates(obj[key]);
        }
        return result;
      }
      return obj;
    };

    serviceData = replaceTemplates(serviceData);

    // Add target if specified
    const target = action.target ? replaceTemplates(action.target) : undefined;

    console.log(`[FolderGalleryCard] Calling ${service}`, { serviceData, target });

    this._hass.callService(domain, serviceName, serviceData, target)
      .then(() => {
        // Visual feedback
        this.showToast(`Action executed: ${serviceName}`);
      })
      .catch(err => {
        console.error('[FolderGalleryCard] Service call failed:', err);
        this.showToast(`Error: ${err.message}`, true);
      });
  }

  showToast(message, isError = false) {
    this.fireEvent('hass-notification', {
      message: message,
      duration: 3000
    });
  }

  fireEvent(type, detail = {}) {
    const event = new CustomEvent(type, {
      bubbles: true,
      composed: true,
      detail
    });
    this.dispatchEvent(event);
  }

  getCardSize() {
    const rows = Math.ceil(this._images.length / this._config.columns);
    return Math.max(1, rows * 2);
  }

  static getConfigElement() {
    return document.createElement('folder-gallery-card-editor');
  }

  static getStubConfig() {
    return {
      title: 'My Gallery',
      folder: '/local/images',
      columns: 4,
      image_height: '150px',
      sensor: 'sensor.folder_images'
    };
  }
}

// Card Editor
class FolderGalleryCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  setConfig(config) {
    this._config = config;
    this.render();
  }

  render() {
    this.shadowRoot.innerHTML = `
      <style>
        .form-row {
          margin-bottom: 12px;
        }
        .form-row label {
          display: block;
          margin-bottom: 4px;
          font-weight: 500;
        }
        .form-row input, .form-row select {
          width: 100%;
          padding: 8px;
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
        }
      </style>
      
      <div class="form-row">
        <label>Title</label>
        <input type="text" id="title" value="${this._config.title || ''}">
      </div>
      
      <div class="form-row">
        <label>Folder Path</label>
        <input type="text" id="folder" value="${this._config.folder || ''}" placeholder="/local/images">
      </div>
      
      <div class="form-row">
        <label>Sensor (provides image list)</label>
        <input type="text" id="sensor" value="${this._config.sensor || ''}" placeholder="sensor.my_images">
      </div>
      
      <div class="form-row">
        <label>Columns</label>
        <input type="number" id="columns" value="${this._config.columns || 4}" min="1" max="10">
      </div>
      
      <div class="form-row">
        <label>Image Height</label>
        <input type="text" id="image_height" value="${this._config.image_height || '150px'}">
      </div>
    `;

    // Add event listeners
    ['title', 'folder', 'sensor', 'columns', 'image_height'].forEach(field => {
      const input = this.shadowRoot.getElementById(field);
      if (input) {
        input.addEventListener('change', (e) => {
          let value = e.target.value;
          if (field === 'columns') value = parseInt(value);
          this.fireEvent('config-changed', { 
            config: { ...this._config, [field]: value } 
          });
        });
      }
    });
  }

  fireEvent(type, detail) {
    const event = new CustomEvent(type, {
      bubbles: true,
      composed: true,
      detail
    });
    this.dispatchEvent(event);
  }
}

// Register elements
customElements.define('folder-gallery-card', FolderGalleryCard);
customElements.define('folder-gallery-card-editor', FolderGalleryCardEditor);

// Register with Lovelace
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'folder-gallery-card',
  name: 'Folder Gallery Card',
  description: 'Display images from a folder with click actions',
  preview: true
});

console.info(
  '%c FOLDER-GALLERY-CARD %c v1.0.0 ',
  'color: white; background: #03a9f4; font-weight: bold;',
  'color: #03a9f4; background: white; font-weight: bold;'
);
