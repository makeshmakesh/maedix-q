// ============================================================================
// Flow Edit Wizard - Mobile Guided Editor
// ============================================================================
// Self-contained wizard that reads/writes the same node data format
// and saves via the same API endpoint as the full editor.

(function() {
    'use strict';

    // --- State ---
    let formNodes = [];
    let wizardSteps = [];
    let wizardCurrentStep = -1; // -1 = summary view
    let hasUnsavedChanges = false;
    let settingsOpen = false;
    let currentSettings = { ...flowSettings };

    const NODE_TYPES = {
        'comment_reply':            { icon: 'bi-chat-dots',        cls: 'comment-reply',   title: 'Reply to Comment' },
        'message_text':             { icon: 'bi-chat-left-text',   cls: 'text-message',    title: 'Send Message' },
        'message_quick_reply':      { icon: 'bi-ui-radios-grid',   cls: 'quick-reply',     title: 'Quick Reply' },
        'message_button_template':  { icon: 'bi-menu-button-wide', cls: 'button-template', title: 'Message + Buttons' },
        'message_link':             { icon: 'bi-link',             cls: 'link-message',    title: 'Send Link' },
        'condition_follower':       { icon: 'bi-person-check',     cls: 'follower-check',  title: 'Follower Check' },
        'condition_user_interacted':{ icon: 'bi-person-lines-fill',cls: 'user-interacted', title: 'Returning User Check' },
        'collect_data':             { icon: 'bi-input-cursor-text',cls: 'collect-data',    title: 'Collect Info' },
        'ai_conversation':          { icon: 'bi-cpu',              cls: 'ai-conversation', title: 'AI Chat' }
    };

    // --- Initialize ---
    initFormNodes();
    buildWizardSteps();
    renderCurrentView();
    attachNavHandlers();

    // =========================================================================
    // Parse existingNodes into formNodes array
    // =========================================================================
    function initFormNodes() {
        formNodes = [];
        const sorted = [...existingNodes].sort((a, b) => a.order - b.order);

        sorted.forEach(dbNode => {
            const node = {
                dbId: dbNode.id,
                type: dbNode.node_type,
                config: { ...dbNode.config },
                quickReplies: (dbNode.quick_replies || []).map(qr => ({
                    title: qr.title || '',
                    payload: qr.payload || '',
                    targetNodeId: qr.target_node_id
                })),
                nextNodeId: dbNode.next_node_id,
                _pos_x: dbNode.config?._pos_x,
                _pos_y: dbNode.config?._pos_y
            };
            delete node.config._pos_x;
            delete node.config._pos_y;
            delete node.config.quick_replies;
            formNodes.push(node);
        });
    }

    // =========================================================================
    // Build wizard steps with smart grouping
    // =========================================================================
    function buildWizardSteps() {
        wizardSteps = [];
        const consumed = new Set();

        formNodes.forEach((node, idx) => {
            if (node.type === 'condition_follower') {
                const trueIdx = findNodeIndex(node.config.true_node_id);
                const falseIdx = findNodeIndex(node.config.false_node_id);
                if (trueIdx !== -1) consumed.add(trueIdx);
                if (falseIdx !== -1) consumed.add(falseIdx);
            }
        });

        formNodes.forEach((node, idx) => {
            if (consumed.has(idx)) return;
            if (node.type === 'condition_user_interacted') return;

            if (node.type === 'condition_follower') {
                const trueIdx = findNodeIndex(node.config.true_node_id);
                const falseIdx = findNodeIndex(node.config.false_node_id);
                wizardSteps.push({
                    type: 'follower_check',
                    nodeIndex: idx,
                    trueNodeIndex: trueIdx,
                    falseNodeIndex: falseIdx
                });
            } else {
                wizardSteps.push({ type: 'single', nodeIndex: idx });
            }
        });
    }

    function findNodeIndex(dbId) {
        if (!dbId) return -1;
        return formNodes.findIndex(n => n.dbId === dbId);
    }

    // =========================================================================
    // Main render dispatcher
    // =========================================================================
    function renderCurrentView() {
        if (wizardCurrentStep === -1) {
            renderSummary();
        } else {
            renderWizardStep();
        }
    }

    // =========================================================================
    // Summary view — simple numbered list with one Edit button
    // =========================================================================
    function renderSummary() {
        const container = document.getElementById('wizardStepContainer');
        const progressBar = document.getElementById('wizardProgressBar');
        const stepCounter = document.getElementById('wizardStepCounter');

        // Update header
        progressBar.style.width = '100%';
        stepCounter.textContent = `${wizardSteps.length} step${wizardSteps.length !== 1 ? 's' : ''} in this flow`;

        // Hide prev/next, show save
        document.getElementById('wizardPrevBtn').style.display = 'none';
        document.getElementById('wizardNextBtn').style.display = 'none';
        const saveBtn = document.getElementById('wizardSaveBtn');
        saveBtn.style.display = 'flex';
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Flow';

        if (wizardSteps.length === 0) {
            container.innerHTML = `
                ${renderSettingsCard()}
                <div class="wizard-step-card">
                    <div class="wizard-step-body" style="padding:24px 16px; text-align:center;">
                        <i class="bi bi-inbox" style="font-size:2.5rem; color:#9ca3af;"></i>
                        <p style="margin:12px 0 0; color:#6b7280;">This flow has no steps yet.</p>
                        <a href="${fullEditorUrl}" style="display:inline-block; margin-top:12px; color:var(--primary); font-weight:600;">
                            Open Full Editor to add steps
                        </a>
                    </div>
                </div>`;
            attachSettingsHandlers();
            return;
        }

        let stepsHtml = '';
        wizardSteps.forEach((step, stepIdx) => {
            stepsHtml += renderSummaryRow(step, stepIdx);
        });

        container.innerHTML = `
            ${renderSettingsCard()}
            <div class="wizard-step-card">
                <div class="wizard-step-header" style="border-bottom: 1px solid #f0f0f0;">
                    <div class="wizard-step-icon" style="width:32px; height:32px; font-size:14px; background:var(--primary, #7c3aed); color:white;">
                        <i class="bi bi-list-check"></i>
                    </div>
                    <div>
                        <div class="wizard-step-title">Flow Steps</div>
                        <div class="wizard-step-subtitle">Here's what happens when someone comments</div>
                    </div>
                </div>
                <div class="wizard-summary-list">
                    ${stepsHtml}
                </div>
                <div style="padding: 12px 16px;">
                    <button class="wizard-edit-all-btn" id="wizardEditAllBtn">
                        <i class="bi bi-pencil-square me-2"></i>Edit Steps
                    </button>
                </div>
            </div>`;

        attachSettingsHandlers();

        document.getElementById('wizardEditAllBtn').addEventListener('click', () => {
            wizardCurrentStep = 0;
            renderCurrentView();
            window.scrollTo(0, 0);
        });
    }

    // =========================================================================
    // Settings Card — collapsible section for flow name, trigger, keywords
    // =========================================================================
    function renderSettingsCard() {
        const s = currentSettings;
        const isKeyword = s.triggerType === 'comment_keyword';
        const triggerLabel = isKeyword ? 'Keyword' : 'Any Comment';
        const kwPreview = isKeyword && s.keywords ? ' \u00b7 ' + s.keywords : '';

        return `
            <div class="wizard-step-card wizard-settings-card">
                <div class="wizard-settings-toggle ${settingsOpen ? 'open' : ''}" id="wizardSettingsToggle" role="button" tabindex="0">
                    <div class="wizard-settings-toggle-left">
                        <div class="wizard-step-icon" style="width:32px; height:32px; font-size:14px; background:#0d6efd; color:white;">
                            <i class="bi bi-gear"></i>
                        </div>
                        <div style="min-width:0;">
                            <div class="wizard-step-title">Flow Settings</div>
                            <div class="wizard-step-subtitle" id="settingsPreview">${esc(triggerLabel + kwPreview)}</div>
                        </div>
                    </div>
                    <i class="bi bi-chevron-down settings-chevron"></i>
                </div>
                <div class="wizard-settings-body" id="wizardSettingsBody" style="display:${settingsOpen ? 'block' : 'none'};">
                    <div class="wizard-field">
                        <label>Flow Name</label>
                        <input type="text" id="settingsTitle" value="${esc(s.title)}" placeholder="My Flow" maxlength="100">
                    </div>
                    <div class="wizard-field">
                        <label>Trigger</label>
                        <select id="settingsTrigger">
                            <option value="comment_keyword" ${isKeyword ? 'selected' : ''}>Comment with Keyword</option>
                            <option value="comment_any" ${!isKeyword ? 'selected' : ''}>Any Comment</option>
                        </select>
                    </div>
                    <div class="wizard-field" id="settingsKeywordsField" style="display:${isKeyword ? 'block' : 'none'};">
                        <label>Keywords</label>
                        <input type="text" id="settingsKeywords" value="${esc(s.keywords)}" placeholder="link, free, send">
                        <div class="field-hint">Comma-separated words that trigger this flow</div>
                    </div>
                    <div class="wizard-field">
                        <div class="wizard-toggle-row">
                            <span>Flow Active</span>
                            <label class="wizard-toggle">
                                <input type="checkbox" id="settingsActive" ${s.isActive ? 'checked' : ''}>
                                <span class="wizard-toggle-slider"></span>
                            </label>
                        </div>
                    </div>
                    <button class="wizard-settings-save-btn" id="wizardSettingsSaveBtn">
                        <i class="bi bi-check-lg me-1"></i>Save Settings
                    </button>
                </div>
            </div>`;
    }

    function attachSettingsHandlers() {
        const toggle = document.getElementById('wizardSettingsToggle');
        const body = document.getElementById('wizardSettingsBody');
        if (!toggle) return;

        toggle.addEventListener('click', () => {
            settingsOpen = !settingsOpen;
            body.style.display = settingsOpen ? 'block' : 'none';
            toggle.classList.toggle('open', settingsOpen);
        });

        // Toggle keywords field visibility
        const triggerSelect = document.getElementById('settingsTrigger');
        triggerSelect.addEventListener('change', () => {
            const kw = document.getElementById('settingsKeywordsField');
            kw.style.display = triggerSelect.value === 'comment_keyword' ? 'block' : 'none';
        });

        // Save settings button
        document.getElementById('wizardSettingsSaveBtn').addEventListener('click', saveSettings);
    }

    function saveSettings() {
        const title = document.getElementById('settingsTitle').value.trim();
        if (!title) {
            showToast('Flow name is required', 'error');
            return;
        }
        if (title.length > 100) {
            showToast('Flow name must be 100 characters or less', 'error');
            return;
        }

        const triggerType = document.getElementById('settingsTrigger').value;
        const keywords = document.getElementById('settingsKeywords')?.value.trim() || '';
        const isActive = document.getElementById('settingsActive').checked;

        const btn = document.getElementById('wizardSettingsSaveBtn');
        btn.disabled = true;
        btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Saving...';

        fetch(`/instagram/flows/${flowId}/wizard/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                title: title,
                trigger_type: triggerType,
                keywords: keywords,
                is_active: isActive
            })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => { throw new Error(data.error || 'Failed to save'); });
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                // Update local state
                currentSettings.title = title;
                currentSettings.triggerType = triggerType;
                currentSettings.keywords = keywords;
                currentSettings.isActive = isActive;

                // Update header
                const headerTitle = document.getElementById('wizardFlowTitle');
                if (headerTitle) headerTitle.textContent = title;

                const badge = document.getElementById('wizardActiveBadge');
                if (badge) {
                    badge.textContent = isActive ? 'Active' : 'Inactive';
                    badge.className = isActive ? 'badge bg-success' : 'badge bg-secondary';
                }

                // Update settings preview
                const preview = document.getElementById('settingsPreview');
                if (preview) {
                    const trigLabel = triggerType === 'comment_keyword' ? 'Keyword' : 'Any Comment';
                    const kwPart = triggerType === 'comment_keyword' && keywords ? ' \u00b7 ' + keywords : '';
                    preview.textContent = trigLabel + kwPart;
                }

                showToast('Settings saved!', 'success');
            } else {
                showToast(data.error || 'Failed to save', 'error');
            }
        })
        .catch(error => {
            showToast('Failed to save: ' + error.message, 'error');
        })
        .finally(() => {
            btn.disabled = false;
            btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Settings';
        });
    }

    function renderSummaryRow(step, stepIdx) {
        const num = stepIdx + 1;
        const isLast = stepIdx === wizardSteps.length - 1;

        if (step.type === 'follower_check') {
            const trueNode = step.trueNodeIndex !== -1 ? formNodes[step.trueNodeIndex] : null;
            const falseNode = step.falseNodeIndex !== -1 ? formNodes[step.falseNodeIndex] : null;
            const trueInfo = trueNode ? (NODE_TYPES[trueNode.type] || { title: 'Action' }) : null;
            const falseInfo = falseNode ? (NODE_TYPES[falseNode.type] || { title: 'Action' }) : null;

            let branchParts = [];
            if (trueInfo) branchParts.push(trueInfo.title);
            if (falseInfo) branchParts.push(falseInfo.title);
            const branchLabel = branchParts.length > 0 ? ' (' + branchParts.join(', ') + ')' : '';

            return `
                <div class="wizard-summary-row ${isLast ? '' : 'has-line'}">
                    <div class="wizard-summary-num">${num}</div>
                    <div class="wizard-summary-row-content">
                        <div class="wizard-summary-row-title">
                            <i class="bi bi-person-check" style="color:#dc3545;"></i>
                            Follower Check${esc(branchLabel)}
                        </div>
                    </div>
                </div>`;
        }

        const node = formNodes[step.nodeIndex];
        const info = NODE_TYPES[node.type] || { icon: 'bi-circle', cls: '', title: 'Step' };
        const label = getSummaryLabel(node);

        return `
            <div class="wizard-summary-row ${isLast ? '' : 'has-line'}">
                <div class="wizard-summary-num">${num}</div>
                <div class="wizard-summary-row-content">
                    <div class="wizard-summary-row-title">
                        <i class="bi ${info.icon}" style="color:${getIconColor(node.type)};"></i>
                        ${esc(label)}
                    </div>
                </div>
            </div>`;
    }

    function getSummaryLabel(node) {
        const c = node.config || {};
        switch (node.type) {
            case 'comment_reply':
                return 'Reply to Comment';
            case 'message_text':
                return 'DM Reply';
            case 'message_link':
                return 'DM Reply (Link)';
            case 'message_button_template': {
                const btnCount = (c.buttons || []).length;
                return `DM Reply (${btnCount} Button${btnCount !== 1 ? 's' : ''})`;
            }
            case 'message_quick_reply': {
                const qrCount = (node.quickReplies || []).length;
                return `DM Reply (${qrCount} Option${qrCount !== 1 ? 's' : ''})`;
            }
            case 'collect_data': {
                const ft = c.field_type || 'info';
                return `Collect ${ft.charAt(0).toUpperCase() + ft.slice(1)}`;
            }
            case 'ai_conversation':
                return 'AI Chat';
            default:
                return NODE_TYPES[node.type]?.title || 'Step';
        }
    }

    function getIconColor(type) {
        const colors = {
            'comment_reply': '#0dcaf0',
            'message_text': '#0d6efd',
            'message_link': '#e6a817',
            'message_button_template': 'var(--primary-dark, #6b21a8)',
            'message_quick_reply': '#198754',
            'collect_data': '#d63384',
            'ai_conversation': '#667eea',
            'condition_follower': '#dc3545'
        };
        return colors[type] || '#6c757d';
    }

    // =========================================================================
    // Render a specific wizard step (editing mode)
    // =========================================================================
    function renderWizardStep() {
        const container = document.getElementById('wizardStepContainer');
        const step = wizardSteps[wizardCurrentStep];
        const total = wizardSteps.length;

        // Update progress
        const pct = total > 1 ? ((wizardCurrentStep + 1) / total) * 100 : 100;
        document.getElementById('wizardProgressBar').style.width = pct + '%';
        document.getElementById('wizardStepCounter').textContent = `Step ${wizardCurrentStep + 1} of ${total}`;

        // Update nav buttons
        const prevBtn = document.getElementById('wizardPrevBtn');
        const nextBtn = document.getElementById('wizardNextBtn');
        const saveBtn = document.getElementById('wizardSaveBtn');

        prevBtn.style.display = 'flex';
        prevBtn.disabled = false; // Always enabled — goes to summary if on step 0

        const isLast = wizardCurrentStep === total - 1;
        nextBtn.style.display = isLast ? 'none' : 'flex';
        saveBtn.style.display = isLast ? 'flex' : 'none';

        if (!step) return;

        if (step.type === 'follower_check') {
            renderFollowerCheckStep(container, step);
        } else {
            renderSingleStep(container, step);
        }

        attachFieldHandlers();
    }

    // =========================================================================
    // Render a single-node step
    // =========================================================================
    function renderSingleStep(container, step) {
        const node = formNodes[step.nodeIndex];
        const info = NODE_TYPES[node.type] || { icon: 'bi-circle', cls: '', title: 'Step' };

        container.innerHTML = `
            <div class="wizard-step-card">
                <div class="wizard-step-header">
                    <div class="wizard-step-icon ${info.cls}">
                        <i class="bi ${info.icon}"></i>
                    </div>
                    <div>
                        <div class="wizard-step-title">${info.title}</div>
                        <div class="wizard-step-subtitle">${getStepSubtitle(node.type)}</div>
                    </div>
                </div>
                <div class="wizard-step-body">
                    ${renderNodeFields(node, step.nodeIndex)}
                </div>
            </div>`;
    }

    // =========================================================================
    // Render follower-check combined step
    // =========================================================================
    function renderFollowerCheckStep(container, step) {
        const trueNode = step.trueNodeIndex !== -1 ? formNodes[step.trueNodeIndex] : null;
        const falseNode = step.falseNodeIndex !== -1 ? formNodes[step.falseNodeIndex] : null;
        const trueInfo = trueNode ? (NODE_TYPES[trueNode.type] || { title: 'Step' }) : null;
        const falseInfo = falseNode ? (NODE_TYPES[falseNode.type] || { title: 'Step' }) : null;

        let trueHtml = '<p style="color:#9ca3af; font-size:13px;">No action configured</p>';
        let falseHtml = '<p style="color:#9ca3af; font-size:13px;">No action configured</p>';

        if (trueNode) {
            trueHtml = `
                <div class="wizard-step-subtitle" style="margin-bottom:8px;">${trueInfo.title}</div>
                ${renderNodeFields(trueNode, step.trueNodeIndex)}`;
        }
        if (falseNode) {
            falseHtml = `
                <div class="wizard-step-subtitle" style="margin-bottom:8px;">${falseInfo.title}</div>
                ${renderNodeFields(falseNode, step.falseNodeIndex)}`;
        }

        container.innerHTML = `
            <div class="wizard-step-card">
                <div class="wizard-step-header">
                    <div class="wizard-step-icon follower-check">
                        <i class="bi bi-person-check"></i>
                    </div>
                    <div>
                        <div class="wizard-step-title">Follower Check</div>
                        <div class="wizard-step-subtitle">Different responses based on follower status</div>
                    </div>
                </div>
                <div class="wizard-step-body">
                    <div class="wizard-follower-section follower-true">
                        <div class="wizard-follower-label">
                            <i class="bi bi-check-circle-fill"></i> If they follow you
                        </div>
                        ${trueHtml}
                    </div>
                    <div class="wizard-follower-section follower-false">
                        <div class="wizard-follower-label">
                            <i class="bi bi-x-circle-fill"></i> If they don't follow
                        </div>
                        ${falseHtml}
                    </div>
                </div>
            </div>`;
    }

    // =========================================================================
    // Render content fields for a node (used by both single & combined steps)
    // =========================================================================
    function renderNodeFields(node, nodeIndex) {
        const c = node.config || {};

        switch (node.type) {
            case 'comment_reply':
                return `
                    <div class="wizard-question">What should we reply to their comment?</div>
                    <div class="wizard-field">
                        <textarea data-node="${nodeIndex}" data-field="text"
                                  placeholder="e.g. Thanks for commenting! Check your DMs 📩">${esc(c.text)}</textarea>
                        <div class="field-hint">This reply appears publicly under their comment</div>
                    </div>`;

            case 'message_text':
                return `
                    <div class="wizard-question">What message should we send?</div>
                    <div class="wizard-field">
                        <textarea data-node="${nodeIndex}" data-field="text"
                                  placeholder="e.g. Hey! Here's what you asked for...">${esc(c.text)}</textarea>
                    </div>`;

            case 'message_link':
                return `
                    <div class="wizard-question">What message and link to send?</div>
                    <div class="wizard-field">
                        <label>Message</label>
                        <textarea data-node="${nodeIndex}" data-field="text"
                                  placeholder="e.g. Here's your link!">${esc(c.text)}</textarea>
                    </div>
                    <div class="wizard-field">
                        <label>URL</label>
                        <input type="url" data-node="${nodeIndex}" data-field="url"
                               value="${esc(c.url)}" placeholder="https://example.com/your-link">
                        <div class="field-hint">Include https://</div>
                    </div>`;

            case 'message_button_template':
                return renderButtonTemplateFields(node, nodeIndex);

            case 'message_quick_reply':
                return renderQuickReplyFields(node, nodeIndex);

            case 'collect_data':
                return renderCollectDataFields(node, nodeIndex);

            case 'ai_conversation':
                return renderAIConversationFields(node);

            default:
                return `<p style="color:#9ca3af; font-size:13px;">This step type can be edited in the full editor.</p>`;
        }
    }

    function renderButtonTemplateFields(node, nodeIndex) {
        const c = node.config || {};
        const buttons = c.buttons || [];

        let buttonsHtml = '';
        buttons.forEach((btn, i) => {
            const isUrl = btn.type === 'web_url';
            buttonsHtml += `
                <div class="wizard-sub-item">
                    <div class="wizard-sub-item-label">
                        <i class="bi bi-hand-index"></i> Button ${i + 1}
                        ${isUrl ? '<span style="color:#0d6efd; font-size:10px;">(URL)</span>' : ''}
                    </div>
                    <input type="text" data-node="${nodeIndex}" data-field="button_title" data-btn-index="${i}"
                           value="${esc(btn.title)}" placeholder="Button text">
                    ${isUrl ? `
                    <input type="url" data-node="${nodeIndex}" data-field="button_url" data-btn-index="${i}"
                           value="${esc(btn.url)}" placeholder="https://..." style="margin-top:6px;">
                    ` : ''}
                </div>`;
        });

        return `
            <div class="wizard-question">What message and buttons to show?</div>
            <div class="wizard-field">
                <label>Message</label>
                <textarea data-node="${nodeIndex}" data-field="text"
                          placeholder="e.g. Choose an option below:">${esc(c.text)}</textarea>
            </div>
            <div class="wizard-sub-items">${buttonsHtml}</div>`;
    }

    function renderQuickReplyFields(node, nodeIndex) {
        const c = node.config || {};
        const qrs = node.quickReplies || [];

        let qrHtml = '';
        qrs.forEach((qr, i) => {
            qrHtml += `
                <div class="wizard-sub-item">
                    <div class="wizard-sub-item-label">
                        <i class="bi bi-reply"></i> Option ${i + 1}
                    </div>
                    <input type="text" data-node="${nodeIndex}" data-field="qr_title" data-qr-index="${i}"
                           value="${esc(qr.title)}" placeholder="Button text">
                </div>`;
        });

        return `
            <div class="wizard-question">What question and options to show?</div>
            <div class="wizard-field">
                <label>Question</label>
                <textarea data-node="${nodeIndex}" data-field="text"
                          placeholder="e.g. What are you interested in?">${esc(c.text)}</textarea>
            </div>
            <div class="wizard-sub-items">${qrHtml}</div>`;
    }

    function renderCollectDataFields(node, nodeIndex) {
        const c = node.config || {};
        const fieldType = c.field_type || 'email';

        return `
            <div class="wizard-question">What info do you want to collect?</div>
            <div class="wizard-field">
                <label>Field type</label>
                <select data-node="${nodeIndex}" data-field="field_type">
                    <option value="email" ${fieldType === 'email' ? 'selected' : ''}>Email</option>
                    <option value="name" ${fieldType === 'name' ? 'selected' : ''}>Name</option>
                    <option value="phone" ${fieldType === 'phone' ? 'selected' : ''}>Phone</option>
                    <option value="custom" ${fieldType === 'custom' ? 'selected' : ''}>Custom</option>
                </select>
            </div>
            <div class="wizard-field">
                <label>Question to ask</label>
                <textarea data-node="${nodeIndex}" data-field="prompt_text"
                          placeholder="e.g. What's your email address?">${esc(c.prompt_text)}</textarea>
            </div>`;
    }

    function renderAIConversationFields(node) {
        const c = node.config || {};
        const configUrl = c.config_url || '#';
        const agentName = c.agent_name || 'Not configured';

        return `
            <div class="wizard-info-card">
                <i class="bi bi-cpu"></i>
                <p>This step uses an AI agent to handle the conversation.<br>
                   <strong>${esc(agentName)}</strong></p>
                <a href="${configUrl}"><i class="bi bi-gear me-1"></i>Set Up AI Agent</a>
            </div>`;
    }

    // =========================================================================
    // Field event handlers — sync input back to formNodes
    // =========================================================================
    function attachFieldHandlers() {
        const container = document.getElementById('wizardStepContainer');

        container.querySelectorAll('[data-node][data-field]').forEach(el => {
            const event = el.tagName === 'SELECT' ? 'change' : 'input';
            el.addEventListener(event, function() {
                hasUnsavedChanges = true;
                const idx = parseInt(this.dataset.node);
                const field = this.dataset.field;
                const node = formNodes[idx];
                if (!node) return;

                if (field === 'text' || field === 'url' || field === 'prompt_text' || field === 'field_type') {
                    node.config[field] = this.value;
                } else if (field === 'button_title') {
                    const btnIdx = parseInt(this.dataset.btnIndex);
                    if (node.config.buttons && node.config.buttons[btnIdx]) {
                        node.config.buttons[btnIdx].title = this.value;
                    }
                } else if (field === 'button_url') {
                    const btnIdx = parseInt(this.dataset.btnIndex);
                    if (node.config.buttons && node.config.buttons[btnIdx]) {
                        node.config.buttons[btnIdx].url = this.value;
                    }
                } else if (field === 'qr_title') {
                    const qrIdx = parseInt(this.dataset.qrIndex);
                    if (node.quickReplies && node.quickReplies[qrIdx]) {
                        node.quickReplies[qrIdx].title = this.value;
                    }
                }
            });
        });
    }

    // =========================================================================
    // Navigation handlers
    // =========================================================================
    function attachNavHandlers() {
        document.getElementById('wizardPrevBtn').addEventListener('click', () => {
            if (wizardCurrentStep > 0) {
                wizardCurrentStep--;
            } else {
                // On step 0, go back to summary
                wizardCurrentStep = -1;
            }
            renderCurrentView();
            window.scrollTo(0, 0);
        });

        document.getElementById('wizardNextBtn').addEventListener('click', () => {
            if (wizardCurrentStep < wizardSteps.length - 1) {
                wizardCurrentStep++;
                renderCurrentView();
                window.scrollTo(0, 0);
            }
        });

        document.getElementById('wizardSaveBtn').addEventListener('click', () => {
            saveWizardFlow();
        });
    }

    // =========================================================================
    // Save — builds same payload as the full editor's saveFormFlow()
    // =========================================================================
    function saveWizardFlow() {
        if (formNodes.length === 0) {
            showToast('No steps to save', 'error');
            return;
        }

        // Build nodes payload
        const nodes = formNodes.map((node, index) => {
            const config = { ...node.config };
            if (config.variations) {
                config.variations = config.variations.filter(v => v && v.trim());
                if (config.variations.length === 0) delete config.variations;
            }

            const nodeData = {
                id: node.dbId || null,
                order: index,
                node_type: node.type,
                config: config,
                quick_replies: [],
                next_node_id: node.nextNodeId || null,
                pos_x: node._pos_x,
                pos_y: node._pos_y
            };

            if (node.type === 'message_quick_reply' && node.quickReplies) {
                nodeData.quick_replies = node.quickReplies.map(qr => ({
                    title: qr.title || '',
                    payload: qr.payload || '',
                    target_node_id: qr.targetNodeId || null
                }));
            }

            return nodeData;
        });

        // Validate text lengths
        const INSTAGRAM_MESSAGE_MAX_LENGTH = 1000;
        for (const node of nodes) {
            const config = node.config || {};
            if (config.text && config.text.length > INSTAGRAM_MESSAGE_MAX_LENGTH) {
                showToast(`Message too long (${config.text.length}/${INSTAGRAM_MESSAGE_MAX_LENGTH} chars). Please shorten it.`, 'error');
                return;
            }
            if (config.prompt_text && config.prompt_text.length > INSTAGRAM_MESSAGE_MAX_LENGTH) {
                showToast(`Question too long (${config.prompt_text.length}/${INSTAGRAM_MESSAGE_MAX_LENGTH} chars). Please shorten it.`, 'error');
                return;
            }
        }

        // Validate required fields
        for (let i = 0; i < nodes.length; i++) {
            const node = nodes[i];
            const config = node.config || {};
            const t = node.node_type;

            if (['message_text', 'message_link', 'message_button_template', 'message_quick_reply', 'comment_reply'].includes(t)) {
                if (!config.text || !config.text.trim()) {
                    showToast('Please fill in the message text for all steps.', 'error');
                    return;
                }
            }
            if (t === 'message_link' && (!config.url || !config.url.trim())) {
                showToast('Please add a URL for the link step.', 'error');
                return;
            }
            if (t === 'collect_data' && (!config.prompt_text || !config.prompt_text.trim())) {
                showToast('Please add a question for the collect info step.', 'error');
                return;
            }
        }

        const saveBtn = document.getElementById('wizardSaveBtn');
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Saving...';

        fetch(`/instagram/flows/${flowId}/save-visual/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ nodes: nodes })
        })
        .then(response => {
            if (response.redirected) {
                throw new Error('Session expired. Please refresh and try again.');
            }
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                throw new Error('Server returned non-JSON response. Please log in again.');
            }
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.error || `HTTP ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                hasUnsavedChanges = false;
                showToast('Flow saved!', 'success');
                // Go back to summary instead of reloading
                wizardCurrentStep = -1;
                renderCurrentView();
                window.scrollTo(0, 0);
            } else {
                showToast(data.error || 'Failed to save', 'error');
                saveBtn.disabled = false;
                saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Flow';
            }
        })
        .catch(error => {
            showToast('Failed to save: ' + error.message, 'error');
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Flow';
        });
    }

    // =========================================================================
    // Helpers
    // =========================================================================
    function esc(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function getStepSubtitle(type) {
        const subs = {
            'comment_reply': 'Reply publicly to their comment',
            'message_text': 'Send a direct message',
            'message_link': 'Send a message with a link',
            'message_button_template': 'Message with clickable buttons',
            'message_quick_reply': 'Ask a question with options',
            'collect_data': 'Ask for their email, name, etc.',
            'ai_conversation': 'AI handles the conversation'
        };
        return subs[type] || '';
    }

    function showToast(message, type) {
        document.querySelectorAll('.wizard-toast').forEach(t => t.remove());

        const toast = document.createElement('div');
        toast.className = `wizard-toast ${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    // =========================================================================
    // Editor Choice Modal
    // =========================================================================
    function isMobile() {
        return window.innerWidth <= 767 || ('ontouchstart' in window && navigator.maxTouchPoints > 0);
    }

    function initEditorChoiceModal() {
        const overlay = document.getElementById('editorChoiceOverlay');
        const choiceView = document.getElementById('editorChoiceView');
        const visualNotice = document.getElementById('visualEditorNotice');
        if (!overlay) return;

        function openModal() {
            choiceView.style.display = '';
            visualNotice.style.display = 'none';
            overlay.classList.add('active');
        }

        function closeModal() {
            overlay.classList.remove('active');
        }

        // Open
        document.getElementById('fullEditorBtn').addEventListener('click', openModal);

        // Close
        document.getElementById('editorChoiceClose').addEventListener('click', closeModal);
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeModal();
        });

        // Choose Form Editor → redirect with ?mode=form
        document.getElementById('chooseFormEditor').addEventListener('click', function() {
            window.location.href = formEditorUrl;
        });

        // Choose Visual Editor
        document.getElementById('chooseVisualEditor').addEventListener('click', function() {
            if (isMobile()) {
                // Mobile → show desktop-only notice with animation
                choiceView.style.display = 'none';
                visualNotice.style.display = '';
            } else {
                // Desktop → go straight to visual editor
                window.location.href = fullEditorUrl;
            }
        });

        // Fallback buttons from visual notice
        document.getElementById('visualFallbackWizardBtn').addEventListener('click', closeModal);
        document.getElementById('visualFallbackFormBtn').addEventListener('click', function() {
            window.location.href = formEditorUrl;
        });
    }

    initEditorChoiceModal();

})();
