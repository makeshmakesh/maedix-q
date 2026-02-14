// Initialize Drawflow
const container = document.getElementById('drawflow');
const editor = new Drawflow(container);

// Configure before starting
editor.reroute = true;
editor.reroute_fix_curvature = true;
editor.force_first_input = false;
editor.editor_mode = 'edit';  // Must be set before start()

// Start the editor
editor.start();


// Set initial zoom
editor.zoom = 0.85;
editor.zoom_refresh();

// Show correct help hint based on device
if ('ontouchstart' in window || navigator.maxTouchPoints > 0) {
    document.getElementById('desktopHint')?.style.setProperty('display', 'none');
    document.getElementById('mobileHint')?.style.setProperty('display', 'block');
}

// Track node data (maps drawflow node id to our data)
const nodeDataMap = {};
let selectedNodeId = null;

// ============================================================================
// Node Template Generation
// ============================================================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function generateNodeHtml(type, data = {}) {
    const headers = {
        'trigger': { class: 'trigger', icon: 'bi-lightning-charge', title: 'Trigger' },
        'comment_reply': { class: 'comment-reply', icon: 'bi-chat-dots', title: 'Comment Reply' },
        'message_text': { class: 'text-message', icon: 'bi-chat-left-text', title: 'Text Message' },
        'message_quick_reply': { class: 'quick-reply', icon: 'bi-ui-radios-grid', title: 'Quick Reply' },
        'message_button_template': { class: 'button-template', icon: 'bi-menu-button-wide', title: 'Button Template' },
        'message_link': { class: 'link-message', icon: 'bi-link', title: 'Link Message' },
        'condition_follower': { class: 'follower-check', icon: 'bi-person-check', title: 'Follower Check' },
        'condition_user_interacted': { class: 'user-interacted', icon: 'bi-person-lines-fill', title: 'Returning User' },
        'collect_data': { class: 'collect-data', icon: 'bi-input-cursor-text', title: 'Collect Data' },
        'ai_conversation': { class: 'ai-conversation', icon: 'bi-cpu', title: 'AI Conversation' }
    };

    const header = headers[type] || { class: '', icon: 'bi-circle', title: 'Node' };

    let bodyHtml = '';
    let outputsHtml = '';

    switch (type) {
        case 'trigger':
            bodyHtml = '<div class="text-preview">Comment received</div>';
            break;

        case 'comment_reply':
        case 'message_text':
            const text = data.text || 'Configure message...';
            bodyHtml = `<div class="text-preview">${escapeHtml(text.substring(0, 35))}${text.length > 35 ? '...' : ''}</div>`;
            break;

        case 'message_link':
            const linkText = data.text || 'Link message';
            bodyHtml = `
                <div class="text-preview">${escapeHtml(linkText.substring(0, 30))}...</div>
                <div class="small text-primary mt-1">${escapeHtml((data.url || '').substring(0, 25))}...</div>
            `;
            break;

        case 'message_quick_reply':
            const qrText = data.text || 'Choose an option...';
            bodyHtml = `<div class="text-preview">${escapeHtml(qrText.substring(0, 35))}...</div>`;

            const qrButtons = data.quick_replies || [];
            if (qrButtons.length > 0) {
                outputsHtml = '<div class="node-outputs">';
                qrButtons.forEach((btn, i) => {
                    outputsHtml += `
                        <div class="output-row" data-output="${i + 1}">
                            <span class="output-label button">${escapeHtml(btn.title || `Button ${i+1}`)}</span>
                            <span class="output-dot blue"></span>
                        </div>
                    `;
                });
                outputsHtml += '</div>';
            }
            break;

        case 'message_button_template':
            const btnText = data.text || 'Choose an option...';
            bodyHtml = `<div class="text-preview">${escapeHtml(btnText.substring(0, 35))}...</div>`;

            // Default type is 'postback' if not specified
            const postbackBtns = (data.buttons || []).filter(b => (b.type || 'postback') === 'postback');
            if (postbackBtns.length > 0) {
                outputsHtml = '<div class="node-outputs">';
                postbackBtns.forEach((btn, i) => {
                    outputsHtml += `
                        <div class="output-row" data-output="${i + 1}">
                            <span class="output-label button">${escapeHtml(btn.title || `Button ${i+1}`)}</span>
                            <span class="output-dot blue"></span>
                        </div>
                    `;
                });
                outputsHtml += '</div>';
            } else {
                // No postback buttons - show single default output
                outputsHtml = '<div class="node-outputs"><div class="output-row" data-output="1"><span class="output-label default">Next</span><span class="output-dot"></span></div></div>';
            }
            break;

        case 'condition_follower':
            bodyHtml = '<div class="text-muted small">Checks if user follows you</div>';
            outputsHtml = `
                <div class="node-outputs">
                    <div class="output-row" data-output="1">
                        <span class="output-label follower"><i class="bi bi-check-circle me-1"></i>Follower</span>
                        <span class="output-dot green"></span>
                    </div>
                    <div class="output-row" data-output="2">
                        <span class="output-label not-follower"><i class="bi bi-x-circle me-1"></i>Not Follower</span>
                        <span class="output-dot red"></span>
                    </div>
                </div>
            `;
            break;

        case 'condition_user_interacted':
            const timePeriodLabels = { 'ever': 'Ever', '24h': 'Last 24h', '7d': 'Last 7 days', '30d': 'Last 30 days' };
            const timePeriod = data.time_period || 'ever';
            bodyHtml = `<div class="text-muted small">Completed flow (${timePeriodLabels[timePeriod] || 'Ever'})</div>`;
            outputsHtml = `
                <div class="node-outputs">
                    <div class="output-row" data-output="1">
                        <span class="output-label follower"><i class="bi bi-arrow-repeat me-1"></i>Returning</span>
                        <span class="output-dot green"></span>
                    </div>
                    <div class="output-row" data-output="2">
                        <span class="output-label not-follower"><i class="bi bi-plus-circle me-1"></i>New User</span>
                        <span class="output-dot red"></span>
                    </div>
                </div>
            `;
            break;

        case 'collect_data':
            const fieldType = data.field_type || 'email';
            const collectLabel = fieldType === 'custom' && data.field_label ? data.field_label : fieldType;
            const prompt = data.prompt_text || 'Enter your info...';
            bodyHtml = `
                <div class="text-preview">Collecting: ${escapeHtml(collectLabel)}</div>
                <div class="small text-muted">${escapeHtml(prompt.substring(0, 30))}...</div>
            `;
            break;

        case 'ai_conversation':
            const agentName = data.agent_name || 'No agent selected';
            const goal = data.goal || 'Configure AI goal...';
            bodyHtml = `
                <div class="text-preview"><i class="bi bi-robot me-1"></i>${escapeHtml(agentName)}</div>
                <div class="small text-muted">${escapeHtml(goal.substring(0, 35))}${goal.length > 35 ? '...' : ''}</div>
            `;
            break;
    }

    return `
        <div class="node-header ${header.class}">
            <i class="bi ${header.icon}"></i>
            <span>${header.title}</span>
        </div>
        <div class="node-body">
            ${bodyHtml}
            ${outputsHtml}
        </div>
    `;
}

// ============================================================================
// Node Creation
// ============================================================================

function addTriggerNode() {
    const html = generateNodeHtml('trigger');
    editor.addNode('trigger', 0, 1, 100, 100, 'trigger', {}, html);
}

function getOutputCount(type, data) {
    switch (type) {
        case 'condition_follower':
            return 2; // Follower / Not Follower

        case 'condition_user_interacted':
            return 2; // Returning User / New User

        case 'message_quick_reply':
            return (data.quick_replies || []).length || 1;

        case 'message_button_template':
            // Default type is 'postback' if not specified
            const postbackBtnsCount = (data.buttons || []).filter(b => (b.type || 'postback') === 'postback').length;
            // One output per postback button, or 1 default if no postback buttons
            return postbackBtnsCount > 0 ? postbackBtnsCount : 1;

        default:
            return 1;
    }
}

function addStepNode(type, x, y, data = {}, dbId = null) {
    const inputs = 1;
    const outputs = getOutputCount(type, data);

    const html = generateNodeHtml(type, data);
    const nodeId = editor.addNode(type, inputs, outputs, x, y, type, { ...data, dbId }, html);

    nodeDataMap[nodeId] = {
        type: type,
        data: data,
        dbId: dbId
    };

    return nodeId;
}

function updateNodeVisual(nodeId) {
    const nodeInfo = nodeDataMap[nodeId];
    if (!nodeInfo) return;

    const newOutputCount = getOutputCount(nodeInfo.type, nodeInfo.data);
    const html = generateNodeHtml(nodeInfo.type, nodeInfo.data);

    // Get current node data from Drawflow
    const currentNode = editor.getNodeFromId(nodeId);
    if (!currentNode) return;

    const currentOutputCount = Object.keys(currentNode.outputs).length;

    // If output count changed, we need to recreate the node
    if (currentOutputCount !== newOutputCount) {
        // Save position
        const posX = currentNode.pos_x;
        const posY = currentNode.pos_y;

        // Save incoming connections (to this node's input)
        // Drawflow connection structure: { node: sourceNodeId, output: outputPortName }
        // Some versions use 'output' directly, others might differ
        const incomingConnections = [];
        Object.entries(currentNode.inputs).forEach(([inputKey, inputData]) => {
            inputData.connections.forEach(conn => {
                incomingConnections.push({
                    fromNode: conn.node,
                    // Try different property names that Drawflow might use
                    fromOutput: conn.output || conn.output_class || Object.keys(conn).find(k => k.startsWith('output')) || 'output_1',
                    toInput: inputKey
                });
            });
        });

        // Save outgoing connections (from this node's outputs)
        // Drawflow connection structure: { node: targetNodeId, input: inputPortName }
        const outgoingConnections = [];
        Object.entries(currentNode.outputs).forEach(([outputKey, outputData]) => {
            outputData.connections.forEach(conn => {
                outgoingConnections.push({
                    toNode: conn.node,
                    // Try different property names that Drawflow might use
                    toInput: conn.input || conn.input_class || Object.keys(conn).find(k => k.startsWith('input')) || 'input_1',
                    fromOutput: outputKey
                });
            });
        });

        // Delete old node
        editor.removeNodeId(`node-${nodeId}`);

        // Create new node with correct output count
        const newNodeId = editor.addNode(
            nodeInfo.type,
            1, // inputs
            newOutputCount,
            posX,
            posY,
            nodeInfo.type,
            { ...nodeInfo.data, dbId: nodeInfo.dbId },
            html
        );

        // Update nodeDataMap
        delete nodeDataMap[nodeId];
        nodeDataMap[newNodeId] = {
            type: nodeInfo.type,
            data: nodeInfo.data,
            dbId: nodeInfo.dbId
        };

        // Use requestAnimationFrame to ensure DOM is ready before restoring connections
        requestAnimationFrame(() => {
            // Restore incoming connections
            incomingConnections.forEach(conn => {
                try {
                    editor.addConnection(conn.fromNode, newNodeId, conn.fromOutput, conn.toInput);
                } catch (e) {
                    // Connection might fail if source node was deleted
                }
            });

            // Restore outgoing connections (only if output still exists)
            outgoingConnections.forEach(conn => {
                // Extract output number from "output_X"
                const outputNum = parseInt(conn.fromOutput.replace('output_', ''));
                if (outputNum <= newOutputCount) {
                    try {
                        editor.addConnection(newNodeId, conn.toNode, conn.fromOutput, conn.toInput);
                    } catch (e) {
                        // Connection might fail if target node was deleted
                    }
                }
            });

            // Update selectedNodeId and edit panel
            if (selectedNodeId == nodeId) {
                selectedNodeId = newNodeId;
                document.getElementById('editNodeId').value = newNodeId;
                // Update visual selection
                document.querySelectorAll('.drawflow-node.selected').forEach(el => el.classList.remove('selected'));
                const newNodeEl = document.getElementById(`node-${newNodeId}`);
                if (newNodeEl) newNodeEl.classList.add('selected');
            }
        });
    } else {
        // Just update HTML if output count is the same
        const nodeElement = document.querySelector(`#node-${nodeId} .drawflow_content_node`);
        if (nodeElement) {
            nodeElement.innerHTML = html;
        }
    }
}

// ============================================================================
// Load Existing Flow
// ============================================================================

function loadExistingFlow() {
    addTriggerNode();

    if (existingNodes.length === 0) return;

    try {
        const sortedNodes = [...existingNodes].sort((a, b) => a.order - b.order);

        const startX = 380;
        const startY = 100;
        const spacingY = 180;

        const dbToDrawflow = {};

        // First pass: create all nodes
        sortedNodes.forEach((node, index) => {
            // Use saved positions if available, otherwise use default layout
            const x = node.config._pos_x !== undefined ? node.config._pos_x : startX;
            const y = node.config._pos_y !== undefined ? node.config._pos_y : startY + (index * spacingY);

            const nodeData = {
                ...node.config,
                quick_replies: node.quick_replies || []
            };
            // Remove position data from nodeData (it's only for visual positioning)
            delete nodeData._pos_x;
            delete nodeData._pos_y;

            const drawflowId = addStepNode(node.node_type, x, y, nodeData, node.id);
            dbToDrawflow[node.id] = drawflowId;
        });

        // Second pass: create connections
        if (sortedNodes.length > 0) {
            const firstNodeDrawflowId = dbToDrawflow[sortedNodes[0].id];
            editor.addConnection(1, firstNodeDrawflowId, 'output_1', 'input_1');
        }

        // Collect all nodes that are targets of branching connections
        const branchTargetNodeIds = new Set();
        sortedNodes.forEach(node => {
            if (node.node_type === 'condition_follower') {
                if (node.config.true_node_id) branchTargetNodeIds.add(node.config.true_node_id);
                if (node.config.false_node_id) branchTargetNodeIds.add(node.config.false_node_id);
            }
            if (node.node_type === 'condition_user_interacted') {
                if (node.config.true_node_id) branchTargetNodeIds.add(node.config.true_node_id);
                if (node.config.false_node_id) branchTargetNodeIds.add(node.config.false_node_id);
            }
            if (node.node_type === 'message_quick_reply' && node.quick_replies) {
                node.quick_replies.forEach(qr => {
                    if (qr.target_node_id) branchTargetNodeIds.add(qr.target_node_id);
                });
            }
            if (node.node_type === 'message_button_template' && node.config?.buttons) {
                node.config.buttons.forEach(btn => {
                    if (btn.target_node_id) branchTargetNodeIds.add(btn.target_node_id);
                });
            }
            // Also mark next_node_id targets so they don't get connected sequentially
            if (node.next_node_id) {
                branchTargetNodeIds.add(node.next_node_id);
            }
        });

        // Connect nodes using next_node_id (explicit connections) or fall back to sequential order
        sortedNodes.forEach((currentNode, i) => {
            const fromId = dbToDrawflow[currentNode.id];

            // Skip branching nodes - they have their own connection logic
            if (currentNode.node_type === 'condition_follower') return;
            if (currentNode.node_type === 'condition_user_interacted') return;
            if (currentNode.node_type === 'message_quick_reply') return;
            if (currentNode.node_type === 'message_button_template') return;

            // Use next_node_id if available (explicit connection)
            if (currentNode.next_node_id && dbToDrawflow[currentNode.next_node_id]) {
                editor.addConnection(fromId, dbToDrawflow[currentNode.next_node_id], 'output_1', 'input_1');
                return;
            }

            // Fall back to sequential connection based on order
            const nextNode = sortedNodes[i + 1];
            if (!nextNode) return;

            // Skip if current node is a target of a branch (don't chain branch targets sequentially)
            if (branchTargetNodeIds.has(currentNode.id)) return;

            const toId = dbToDrawflow[nextNode.id];
            if (fromId && toId) {
                editor.addConnection(fromId, toId, 'output_1', 'input_1');
            }
        });

        // Handle branching connections
        sortedNodes.forEach(node => {
            const fromId = dbToDrawflow[node.id];

            if (node.node_type === 'condition_follower') {
                // Follower branch (output_1)
                if (node.config.true_node_id && dbToDrawflow[node.config.true_node_id]) {
                    editor.addConnection(fromId, dbToDrawflow[node.config.true_node_id], 'output_1', 'input_1');
                }
                // Not follower branch (output_2)
                if (node.config.false_node_id && dbToDrawflow[node.config.false_node_id]) {
                    editor.addConnection(fromId, dbToDrawflow[node.config.false_node_id], 'output_2', 'input_1');
                }
            }

            if (node.node_type === 'condition_user_interacted') {
                // Returning user branch (output_1)
                if (node.config.true_node_id && dbToDrawflow[node.config.true_node_id]) {
                    editor.addConnection(fromId, dbToDrawflow[node.config.true_node_id], 'output_1', 'input_1');
                }
                // New user branch (output_2)
                if (node.config.false_node_id && dbToDrawflow[node.config.false_node_id]) {
                    editor.addConnection(fromId, dbToDrawflow[node.config.false_node_id], 'output_2', 'input_1');
                }
            }

            // Quick reply button branching
            if (node.node_type === 'message_quick_reply' && node.quick_replies) {
                node.quick_replies.forEach((qr, i) => {
                    if (qr.target_node_id && dbToDrawflow[qr.target_node_id]) {
                        try {
                            editor.addConnection(fromId, dbToDrawflow[qr.target_node_id], `output_${i + 1}`, 'input_1');
                        } catch (e) {
                            // Connection might fail if node doesn't exist
                        }
                    }
                });
            }

            // Button template postback branching
            if (node.node_type === 'message_button_template' && node.config?.buttons) {
                // Default type is 'postback' if not specified
                const postbackButtons = node.config.buttons.filter(b => (b.type || 'postback') === 'postback');
                postbackButtons.forEach((btn, i) => {
                    if (btn.target_node_id && dbToDrawflow[btn.target_node_id]) {
                        editor.addConnection(fromId, dbToDrawflow[btn.target_node_id], `output_${i + 1}`, 'input_1');
                    }
                });
            }
        });

    } catch (error) {
        showToast('Error loading flow: ' + error.message, 'error');
    }
}

// ============================================================================
// Event Handlers
// ============================================================================

editor.on('nodeSelected', function(nodeId) {
    selectedNodeId = nodeId;
    showEditPanel(nodeId);
});

editor.on('nodeUnselected', function() {
    selectedNodeId = null;
    hideEditPanel();
});

function showEditPanel(nodeId) {
    const nodeInfo = editor.getNodeFromId(nodeId);
    if (!nodeInfo || nodeInfo.name === 'trigger') {
        hideEditPanel();
        return;
    }

    document.getElementById('noSelectionPanel').classList.remove('active');
    document.getElementById('editPanel').classList.add('active');

    document.getElementById('editNodeId').value = nodeId;
    document.getElementById('editNodeType').value = nodeInfo.name;

    const data = nodeDataMap[nodeId]?.data || nodeInfo.data || {};
    const dbId = nodeDataMap[nodeId]?.dbId || null;
    renderConfigFields(nodeInfo.name, data, dbId);

    const titles = {
        'comment_reply': 'Comment Reply',
        'message_text': 'Text Message',
        'message_quick_reply': 'Quick Reply',
        'message_button_template': 'Button Template',
        'message_link': 'Link Message',
        'condition_follower': 'Follower Check',
        'condition_user_interacted': 'Returning User',
        'collect_data': 'Collect Data',
        'ai_conversation': 'AI Conversation'
    };
    document.getElementById('editPanelTitle').textContent = titles[nodeInfo.name] || 'Edit Node';
}

function hideEditPanel() {
    document.getElementById('editPanel').classList.remove('active');
    document.getElementById('noSelectionPanel').classList.add('active');
}

// ============================================================================
// Config Fields Rendering
// ============================================================================

function renderConfigFields(nodeType, data, dbId = null) {
    const container = document.getElementById('nodeConfigFields');
    let html = '';

    // Helper function to build variations section
    function buildVisualVariationsSection(variations) {
        const hasVariations = variations && variations.length > 0;
        const variationsHtml = (variations || []).map((v, i) => `
            <div class="input-group mb-2 variation-row">
                <textarea class="form-control form-control-sm" name="variation_${i}" rows="2" placeholder="Alternative ${i + 1}">${escapeHtml(v || '')}</textarea>
                <button type="button" class="btn btn-outline-danger btn-sm remove-variation"><i class="bi bi-x"></i></button>
            </div>
        `).join('');

        return `
            <div class="mb-3 visual-variations-section">
                <div class="d-flex align-items-center justify-content-between mb-2">
                    <button type="button" class="btn btn-sm ${hasVariations ? 'btn-secondary' : 'btn-outline-secondary'}" id="toggleVariationsBtn">
                        <i class="bi bi-shuffle me-1"></i>Variations ${hasVariations ? `(${variations.length})` : ''}
                    </button>
                </div>
                <div id="variationsContainer" class="${hasVariations ? '' : 'd-none'}">
                    <div id="variationsList">${variationsHtml}</div>
                    <button type="button" class="btn btn-outline-primary btn-sm" id="addVariationBtn">
                        <i class="bi bi-plus me-1"></i>Add Variation
                    </button>
                    <small class="text-muted d-block mt-2">
                        <i class="bi bi-info-circle me-1"></i>If variations exist, one is randomly selected. Main message is ignored.
                    </small>
                </div>
            </div>
        `;
    }

    switch (nodeType) {
        case 'comment_reply':
        case 'message_text':
            html = `
                <div class="mb-3">
                    <label class="form-label">Message Text</label>
                    <textarea class="form-control" name="text" rows="3" required>${data.text || ''}</textarea>
                </div>
                ${buildVisualVariationsSection(data.variations)}
            `;
            break;

        case 'message_quick_reply':
            html = `
                <div class="mb-3">
                    <label class="form-label">Message Text</label>
                    <textarea class="form-control" name="text" rows="2" required>${data.text || ''}</textarea>
                </div>
                ${buildVisualVariationsSection(data.variations)}
                <div class="mb-3">
                    <label class="form-label">Quick Reply Buttons</label>
                    <small class="text-muted d-block mb-2">Each button creates an output for branching</small>
                    <div id="qrButtonsContainer">
                        ${(data.quick_replies || []).map((qr, i) => `
                            <div class="input-group mb-2 qr-row">
                                <input type="text" class="form-control" name="qr_title_${i}" value="${escapeHtml(qr.title || '')}" placeholder="Button text" maxlength="20">
                                <button type="button" class="btn btn-outline-danger remove-qr"><i class="bi bi-x"></i></button>
                            </div>
                        `).join('')}
                    </div>
                    <button type="button" class="btn btn-outline-primary btn-sm" id="addQrBtn">
                        <i class="bi bi-plus me-1"></i>Add Button
                    </button>
                    <small class="text-muted d-block mt-1">Max 13 buttons, 20 chars each</small>
                </div>
                <div class="alert alert-info small">
                    <i class="bi bi-info-circle me-1"></i>
                    After saving, each button will have its own output. Connect them to different nodes for branching.
                </div>
            `;
            break;

        case 'message_button_template':
            html = `
                <div class="mb-3">
                    <label class="form-label">Message Text</label>
                    <textarea class="form-control" name="text" rows="2" required>${data.text || ''}</textarea>
                </div>
                ${buildVisualVariationsSection(data.variations)}
                <div class="mb-3">
                    <label class="form-label">Buttons (max 3)</label>
                    <small class="text-muted d-block mb-2">Action buttons allow flow branching</small>
                    <div id="btnTemplateContainer">
                        ${(data.buttons || []).map((btn, i) => `
                            <div class="card mb-2 btn-row">
                                <div class="card-body p-2">
                                    <div class="row g-2">
                                        <div class="col-4">
                                            <select class="form-select form-select-sm btn-type" name="btn_type_${i}">
                                                <option value="postback" ${(btn.type || 'postback') === 'postback' ? 'selected' : ''}>Action</option>
                                                <option value="web_url" ${btn.type === 'web_url' ? 'selected' : ''}>URL</option>
                                            </select>
                                        </div>
                                        <div class="col-6">
                                            <input type="text" class="form-control form-control-sm" name="btn_title_${i}" value="${escapeHtml(btn.title || '')}" placeholder="Button text" maxlength="20">
                                        </div>
                                        <div class="col-2">
                                            <button type="button" class="btn btn-outline-danger btn-sm remove-btn w-100"><i class="bi bi-x"></i></button>
                                        </div>
                                    </div>
                                    <input type="url" class="form-control form-control-sm btn-value mt-2 ${btn.type === 'web_url' ? '' : 'd-none'}"
                                           name="btn_url_${i}"
                                           value="${escapeHtml(btn.url || '')}"
                                           placeholder="https://...">
                                    <input type="hidden" name="btn_payload_${i}" value="${escapeHtml(btn.payload || `btn_${i}`)}">
                                </div>
                            </div>
                        `).join('')}
                    </div>
                    <button type="button" class="btn btn-outline-primary btn-sm" id="addBtnTemplateBtn">
                        <i class="bi bi-plus me-1"></i>Add Button
                    </button>
                </div>
                <div class="alert alert-info small">
                    <i class="bi bi-info-circle me-1"></i>
                    Action buttons allow branching. URL buttons open a link.
                </div>
            `;
            break;

        case 'message_link':
            html = `
                <div class="mb-3">
                    <label class="form-label">Message Text</label>
                    <textarea class="form-control" name="text" rows="2">${data.text || ''}</textarea>
                </div>
                ${buildVisualVariationsSection(data.variations)}
                <div class="mb-3">
                    <label class="form-label">URL</label>
                    <input type="url" class="form-control" name="url" value="${data.url || ''}" required placeholder="https://...">
                </div>
            `;
            break;

        case 'condition_follower':
            html = `
                <div class="alert alert-warning small mb-3">
                    <i class="bi bi-exclamation-triangle me-1"></i>
                    <strong>Requires user interaction first!</strong><br>
                    This node only works if a Quick Reply or Button Template appears <em>before</em> it in the flow, or if the user has already messaged you in this session.
                </div>
                <div class="alert alert-info small mb-3">
                    <i class="bi bi-info-circle me-1"></i>
                    This node checks if the user follows your account.
                </div>
                <div class="mb-3">
                    <strong>Outputs:</strong>
                    <div class="mt-2">
                        <div class="d-flex align-items-center mb-2">
                            <span class="output-dot green me-2" style="display:inline-block;width:12px;height:12px;border-radius:50%;"></span>
                            <span><strong>Follower</strong> - User follows you</span>
                        </div>
                        <div class="d-flex align-items-center">
                            <span class="output-dot red me-2" style="display:inline-block;width:12px;height:12px;border-radius:50%;background:#dc3545;"></span>
                            <span><strong>Not Follower</strong> - User doesn't follow</span>
                        </div>
                    </div>
                </div>
                <p class="text-muted small">Connect the green output to the path for followers, and the red output for non-followers.</p>
            `;
            break;

        case 'condition_user_interacted':
            html = `
                <div class="alert alert-info small mb-3">
                    <i class="bi bi-info-circle me-1"></i>
                    Checks if user has previously completed this flow.
                </div>
                <div class="mb-3">
                    <label class="form-label">Time Period</label>
                    <select class="form-select" name="time_period">
                        <option value="ever" ${data.time_period === 'ever' || !data.time_period ? 'selected' : ''}>Ever</option>
                        <option value="24h" ${data.time_period === '24h' ? 'selected' : ''}>Last 24 hours</option>
                        <option value="7d" ${data.time_period === '7d' ? 'selected' : ''}>Last 7 days</option>
                        <option value="30d" ${data.time_period === '30d' ? 'selected' : ''}>Last 30 days</option>
                    </select>
                    <small class="text-muted">Lookback period</small>
                </div>
                <div class="mb-3">
                    <strong>Outputs:</strong>
                    <div class="mt-2">
                        <div class="d-flex align-items-center mb-2">
                            <span class="output-dot green me-2" style="display:inline-block;width:12px;height:12px;border-radius:50%;"></span>
                            <span><strong>Returning User</strong> - Has completed before</span>
                        </div>
                        <div class="d-flex align-items-center">
                            <span class="output-dot red me-2" style="display:inline-block;width:12px;height:12px;border-radius:50%;background:#dc3545;"></span>
                            <span><strong>New User</strong> - First time</span>
                        </div>
                    </div>
                </div>
                <p class="text-muted small">Connect the green output for returning users, red for new users.</p>
            `;
            break;

        case 'collect_data':
            const collectFieldType = data.field_type || 'email';
            const isCustomType = collectFieldType === 'custom';
            const autoVarName = isCustomType
                ? (data.variable_name || `custom_${Math.random().toString(36).substring(2, 8)}`)
                : `collected_${collectFieldType}`;
            const fieldLabel = data.field_label || '';
            html = `
                <div class="mb-3">
                    <label class="form-label">Data Type</label>
                    <select class="form-select" name="field_type" id="collectFieldType" required>
                        <option value="name" ${collectFieldType === 'name' ? 'selected' : ''}>Name</option>
                        <option value="email" ${collectFieldType === 'email' ? 'selected' : ''}>Email</option>
                        <option value="phone" ${collectFieldType === 'phone' ? 'selected' : ''}>Phone</option>
                        <option value="custom" ${collectFieldType === 'custom' ? 'selected' : ''}>Custom</option>
                    </select>
                </div>
                <div class="mb-3 ${isCustomType ? '' : 'd-none'}" id="customLabelGroup">
                    <label class="form-label">Field Label <small class="text-muted">(shown in Leads)</small></label>
                    <input type="text" class="form-control" name="field_label" id="collectFieldLabel" value="${fieldLabel}" placeholder="e.g. Company Name" ${isCustomType ? 'required' : ''}>
                </div>
                <div class="mb-3">
                    <label class="form-label">Prompt Message</label>
                    <textarea class="form-control" name="prompt_text" rows="2" required placeholder="What's your email?">${data.prompt_text || ''}</textarea>
                </div>
                <input type="hidden" name="variable_name" id="collectVarName" value="${autoVarName}">
            `;
            break;

        case 'ai_conversation':
            if (dbId) {
                // Node is saved - show configure button
                const configUrl = `/instagram/ai/node/${dbId}/config/`;
                const agentDisplay = data.agent_name || 'No agent selected';
                const goalDisplay = data.goal || 'No goal configured';
                html = `
                    <div class="alert alert-info small mb-3">
                        <i class="bi bi-cpu me-1"></i>
                        AI-powered conversation node. The AI will handle the conversation dynamically.
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Agent</label>
                        <div class="form-control bg-light">${escapeHtml(agentDisplay)}</div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Goal</label>
                        <div class="form-control bg-light" style="min-height:60px;white-space:pre-wrap;">${escapeHtml(goalDisplay)}</div>
                    </div>
                    <div class="d-grid">
                        <a href="${configUrl}" class="btn btn-primary">
                            <i class="bi bi-gear me-2"></i>Configure AI Node
                        </a>
                    </div>
                    <p class="text-muted small mt-3">
                        <i class="bi bi-info-circle me-1"></i>
                        Click the button above to configure the agent, goal, knowledge bases, and data collection schema.
                    </p>
                `;
            } else {
                // Node is not saved yet - show save message
                html = `
                    <div class="alert alert-warning small mb-3">
                        <i class="bi bi-exclamation-triangle me-1"></i>
                        <strong>Save Required</strong>
                    </div>
                    <p class="text-muted">
                        This AI node needs to be saved before you can configure it.
                    </p>
                    <ol class="text-muted small">
                        <li>Click <strong>Save</strong> button above</li>
                        <li>Then click on this node again to configure</li>
                    </ol>
                    <div class="d-grid">
                        <button type="button" class="btn btn-secondary" disabled>
                            <i class="bi bi-gear me-2"></i>Configure AI Node
                        </button>
                    </div>
                    <p class="text-muted small mt-3">
                        <i class="bi bi-info-circle me-1"></i>
                        After saving, you'll be able to select an agent, set goals, and configure data collection.
                    </p>
                `;
            }
            break;
    }

    container.innerHTML = html;
    setupDynamicFormHandlers();
}

// ============================================================================
// Dynamic Form Handlers
// ============================================================================

function setupDynamicFormHandlers() {
    // Quick Reply add button
    const addQrBtn = document.getElementById('addQrBtn');
    if (addQrBtn) {
        addQrBtn.addEventListener('click', function() {
            const container = document.getElementById('qrButtonsContainer');
            const count = container.querySelectorAll('.qr-row').length;
            if (count >= 13) {
                alert('Maximum 13 quick reply buttons');
                return;
            }
            const div = document.createElement('div');
            div.className = 'input-group mb-2 qr-row';
            div.innerHTML = `
                <input type="text" class="form-control" name="qr_title_${count}" placeholder="Button text" maxlength="20">
                <button type="button" class="btn btn-outline-danger remove-qr"><i class="bi bi-x"></i></button>
            `;
            container.appendChild(div);
            setupRemoveHandlers();
        });
    }

    // Button Template add button
    const addBtnTemplateBtn = document.getElementById('addBtnTemplateBtn');
    if (addBtnTemplateBtn) {
        addBtnTemplateBtn.addEventListener('click', function() {
            const container = document.getElementById('btnTemplateContainer');
            const count = container.querySelectorAll('.btn-row').length;
            if (count >= 3) {
                alert('Maximum 3 buttons for button template');
                return;
            }
            const div = document.createElement('div');
            div.className = 'card mb-2 btn-row';
            div.innerHTML = `
                <div class="card-body p-2">
                    <div class="row g-2">
                        <div class="col-4">
                            <select class="form-select form-select-sm btn-type" name="btn_type_${count}">
                                <option value="postback" selected>Action</option>
                                <option value="web_url">URL</option>
                            </select>
                        </div>
                        <div class="col-6">
                            <input type="text" class="form-control form-control-sm" name="btn_title_${count}" placeholder="Button text" maxlength="20">
                        </div>
                        <div class="col-2">
                            <button type="button" class="btn btn-outline-danger btn-sm remove-btn w-100"><i class="bi bi-x"></i></button>
                        </div>
                    </div>
                    <input type="url" class="form-control form-control-sm btn-value mt-2 d-none" name="btn_url_${count}" placeholder="https://...">
                    <input type="hidden" name="btn_payload_${count}" value="btn_${count}">
                </div>
            `;
            container.appendChild(div);
            setupRemoveHandlers();
            setupBtnTypeHandlers();
        });
    }

    // Variations toggle button
    const toggleVariationsBtn = document.getElementById('toggleVariationsBtn');
    if (toggleVariationsBtn) {
        toggleVariationsBtn.addEventListener('click', function() {
            const container = document.getElementById('variationsContainer');
            container.classList.toggle('d-none');
            this.classList.toggle('btn-secondary');
            this.classList.toggle('btn-outline-secondary');
        });
    }

    // Add variation button
    const addVariationBtn = document.getElementById('addVariationBtn');
    if (addVariationBtn) {
        addVariationBtn.addEventListener('click', function() {
            const list = document.getElementById('variationsList');
            const count = list.querySelectorAll('.variation-row').length;
            if (count >= 10) {
                alert('Maximum 10 variations');
                return;
            }
            const div = document.createElement('div');
            div.className = 'input-group mb-2 variation-row';
            div.innerHTML = `
                <textarea class="form-control form-control-sm" name="variation_${count}" rows="2" placeholder="Alternative ${count + 1}"></textarea>
                <button type="button" class="btn btn-outline-danger btn-sm remove-variation"><i class="bi bi-x"></i></button>
            `;
            list.appendChild(div);
            setupRemoveHandlers();
            // Update toggle button text
            updateVariationsCount();
        });
    }

    setupRemoveHandlers();
    setupBtnTypeHandlers();
    setupCollectDataHandler();
}

function updateVariationsCount() {
    const list = document.getElementById('variationsList');
    const toggleBtn = document.getElementById('toggleVariationsBtn');
    if (list && toggleBtn) {
        const count = list.querySelectorAll('.variation-row').length;
        toggleBtn.innerHTML = `<i class="bi bi-shuffle me-1"></i>Variations ${count > 0 ? `(${count})` : ''}`;
    }
}

function setupCollectDataHandler() {
    const fieldTypeSelect = document.getElementById('collectFieldType');
    const varNameInput = document.getElementById('collectVarName');
    const customLabelGroup = document.getElementById('customLabelGroup');
    const fieldLabelInput = document.getElementById('collectFieldLabel');

    if (fieldTypeSelect && varNameInput) {
        fieldTypeSelect.addEventListener('change', function() {
            const isCustom = this.value === 'custom';
            if (isCustom) {
                // Custom: show label field, generate random var name
                if (customLabelGroup) customLabelGroup.classList.remove('d-none');
                if (fieldLabelInput) fieldLabelInput.required = true;
                // Generate random variable name if empty
                if (!varNameInput.value || !varNameInput.value.startsWith('custom_')) {
                    varNameInput.value = `custom_${Math.random().toString(36).substring(2, 8)}`;
                }
            } else {
                // Preset types: hide label field, auto-generate var name
                if (customLabelGroup) customLabelGroup.classList.add('d-none');
                if (fieldLabelInput) {
                    fieldLabelInput.required = false;
                    fieldLabelInput.value = '';
                }
                varNameInput.value = `collected_${this.value}`;
            }
        });
    }
}

function setupRemoveHandlers() {
    document.querySelectorAll('.remove-qr, .remove-btn, .remove-variation').forEach(btn => {
        btn.onclick = function() {
            this.closest('.qr-row, .btn-row, .variation-row').remove();
            updateVariationsCount();
        };
    });
}

function setupBtnTypeHandlers() {
    document.querySelectorAll('.btn-type').forEach(select => {
        select.onchange = function() {
            const row = this.closest('.btn-row');
            const urlInput = row.querySelector('.btn-value');

            if (this.value === 'web_url') {
                urlInput.classList.remove('d-none');
            } else {
                urlInput.classList.add('d-none');
            }
        };
    });
}

// ============================================================================
// Form Submission
// ============================================================================

document.getElementById('nodeEditForm').addEventListener('submit', function(e) {
    e.preventDefault();

    const nodeId = parseInt(document.getElementById('editNodeId').value, 10);
    const nodeType = document.getElementById('editNodeType').value;
    const formData = new FormData(this);

    const config = {};

    // Helper function to collect variations (filters out empty ones)
    function collectVariations() {
        const variations = [];
        const textareas = document.querySelectorAll('.variation-row textarea');
        textareas.forEach((textarea) => {
            if (textarea.value.trim()) {
                variations.push(textarea.value.trim());
            }
        });
        return variations.length > 0 ? variations : undefined;
    }

    switch (nodeType) {
        case 'comment_reply':
        case 'message_text':
            config.text = formData.get('text');
            config.variations = collectVariations();
            break;

        case 'message_quick_reply':
            config.text = formData.get('text');
            config.variations = collectVariations();
            config.quick_replies = [];
            document.querySelectorAll('.qr-row').forEach((row, i) => {
                const title = row.querySelector('input').value;
                if (title) {
                    config.quick_replies.push({
                        title: title,
                        payload: `qr_${i}`
                    });
                }
            });
            break;

        case 'message_button_template':
            config.text = formData.get('text');
            config.variations = collectVariations();
            config.buttons = [];
            document.querySelectorAll('.btn-row').forEach((row, i) => {
                const type = row.querySelector('.btn-type').value;
                const title = row.querySelector('input[name^="btn_title"]').value;
                const urlInput = row.querySelector('input[name^="btn_url"]');
                const payloadInput = row.querySelector('input[name^="btn_payload"]');
                if (title) {
                    const btn = { type, title };
                    if (type === 'web_url') {
                        btn.url = urlInput ? urlInput.value : '';
                    } else {
                        btn.payload = payloadInput ? payloadInput.value : `btn_${i}`;
                    }
                    config.buttons.push(btn);
                }
            });
            break;

        case 'message_link':
            config.text = formData.get('text');
            config.variations = collectVariations();
            config.url = formData.get('url');
            break;

        case 'collect_data':
            config.field_type = formData.get('field_type');
            config.prompt_text = formData.get('prompt_text');
            config.variable_name = formData.get('variable_name');
            config.field_label = formData.get('field_label') || '';
            break;

        case 'condition_user_interacted':
            config.time_period = formData.get('time_period') || 'ever';
            break;

        case 'ai_conversation':
            // AI node config is handled on a separate page
            // Preserve existing config data
            config = { ...nodeDataMap[nodeId]?.data };
            break;
    }

    // Update node data
    nodeDataMap[nodeId] = {
        type: nodeType,
        data: config,
        dbId: nodeDataMap[nodeId]?.dbId
    };

    // Update visual
    updateNodeVisual(nodeId);

    showToast('Node updated. Save flow to persist changes.');
});

// Delete node
document.getElementById('deleteNodeBtn').addEventListener('click', function() {
    if (!selectedNodeId) return;

    const nodeInfo = nodeDataMap[selectedNodeId];
    if (!nodeInfo) return;

    // Check if deleting an interaction node when follower check depends on it
    if (nodeInfo.type === 'message_quick_reply' || nodeInfo.type === 'message_button_template') {
        const hasFollowerCheck = Object.values(nodeDataMap).some(n => n.type === 'condition_follower');
        const interactionCount = Object.values(nodeDataMap).filter(n =>
            n.type === 'message_quick_reply' || n.type === 'message_button_template'
        ).length;

        if (hasFollowerCheck && interactionCount <= 1) {
            showToast('Cannot delete: Follower Check node requires at least one Quick Reply or Button Template.', 'error');
            return;
        }
    }

    if (confirm('Delete this node?')) {
        editor.removeNodeId(`node-${selectedNodeId}`);
        delete nodeDataMap[selectedNodeId];
        hideEditPanel();
        showToast('Node deleted');

        // Update palette state after deletion
        updateFollowerCheckPaletteState();
    }
});

// ============================================================================
// Validation Helpers
// ============================================================================

function hasInteractionNode() {
    // Check if flow has any quick reply or button template nodes
    return Object.values(nodeDataMap).some(node =>
        node.type === 'message_quick_reply' || node.type === 'message_button_template'
    );
}

function updateFollowerCheckPaletteState() {
    const followerCheckItem = document.querySelector('.palette-item[data-node="condition_follower"]');
    if (!followerCheckItem) return;

    const smallText = followerCheckItem.querySelector('small');

    if (hasInteractionNode()) {
        followerCheckItem.classList.remove('disabled');
        followerCheckItem.setAttribute('draggable', 'true');
        followerCheckItem.title = 'Check if user follows your account';
        if (smallText) smallText.style.display = 'none';
    } else {
        followerCheckItem.classList.add('disabled');
        followerCheckItem.setAttribute('draggable', 'false');
        followerCheckItem.title = 'Add a Quick Reply or Button Template first (required for user consent)';
        if (smallText) smallText.style.display = 'block';
    }
}

// ============================================================================
// Drag & Drop (Desktop)
// ============================================================================

// Attach drag event to ALL palette items (including initially disabled ones)
document.querySelectorAll('.palette-item').forEach(item => {
    item.addEventListener('dragstart', function(e) {
        if (this.classList.contains('disabled') || this.getAttribute('draggable') === 'false') {
            e.preventDefault();
            return;
        }
        e.dataTransfer.setData('node-type', this.dataset.node);
    });
});

container.addEventListener('dragover', function(e) {
    e.preventDefault();
});

container.addEventListener('drop', function(e) {
    e.preventDefault();
    const nodeType = e.dataTransfer.getData('node-type');
    if (!nodeType) return;

    // Validate follower check node
    if (nodeType === 'condition_follower' && !hasInteractionNode()) {
        showToast('Add a Quick Reply or Button Template first. Follower check requires user interaction for consent.', 'error');
        return;
    }

    const rect = container.getBoundingClientRect();
    const x = (e.clientX - rect.left - editor.precanvas.getBoundingClientRect().left + rect.left) / editor.zoom;
    const y = (e.clientY - rect.top - editor.precanvas.getBoundingClientRect().top + rect.top) / editor.zoom;

    addStepNode(nodeType, x, y, {});
    showToast('Node added - click to configure, then connect outputs');

    // Update palette state after adding node
    updateFollowerCheckPaletteState();
});

// ============================================================================
// Touch Drag & Drop (Mobile)
// ============================================================================

let touchDragData = null;
let touchGhost = null;

function createTouchGhost(item) {
    const ghost = document.createElement('div');
    ghost.className = 'touch-drag-ghost';
    ghost.innerHTML = item.innerHTML;
    ghost.style.cssText = `
        position: fixed;
        z-index: 10000;
        pointer-events: none;
        padding: 10px 15px;
        background: var(--bs-primary);
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        opacity: 0.9;
        transform: translate(-50%, -50%);
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px;
    `;
    document.body.appendChild(ghost);
    return ghost;
}

function removeTouchGhost() {
    if (touchGhost) {
        touchGhost.remove();
        touchGhost = null;
    }
    touchDragData = null;
}

document.querySelectorAll('.palette-item').forEach(item => {
    item.addEventListener('touchstart', function(e) {
        if (this.classList.contains('disabled')) return;

        const nodeType = this.dataset.node;
        if (!nodeType) return;

        touchDragData = { nodeType };
        touchGhost = createTouchGhost(this);

        const touch = e.touches[0];
        touchGhost.style.left = touch.clientX + 'px';
        touchGhost.style.top = touch.clientY + 'px';

        // Prevent scrolling while dragging
        e.preventDefault();
    }, { passive: false });

    item.addEventListener('touchmove', function(e) {
        if (!touchDragData || !touchGhost) return;

        const touch = e.touches[0];
        touchGhost.style.left = touch.clientX + 'px';
        touchGhost.style.top = touch.clientY + 'px';

        e.preventDefault();
    }, { passive: false });

    item.addEventListener('touchend', function(e) {
        if (!touchDragData) return;

        const touch = e.changedTouches[0];
        const dropTarget = document.elementFromPoint(touch.clientX, touch.clientY);

        // Check if dropped on the drawflow container or its children
        if (dropTarget && (dropTarget.closest('#drawflow') || dropTarget.id === 'drawflow')) {
            const nodeType = touchDragData.nodeType;

            // Validate follower check node
            if (nodeType === 'condition_follower' && !hasInteractionNode()) {
                showToast('Add a Quick Reply or Button Template first. Follower check requires user interaction for consent.', 'error');
                removeTouchGhost();
                return;
            }

            const rect = container.getBoundingClientRect();
            const x = (touch.clientX - rect.left - editor.precanvas.getBoundingClientRect().left + rect.left) / editor.zoom;
            const y = (touch.clientY - rect.top - editor.precanvas.getBoundingClientRect().top + rect.top) / editor.zoom;

            addStepNode(nodeType, x, y, {});
            showToast('Node added - tap to configure');
            updateFollowerCheckPaletteState();
        }

        removeTouchGhost();
    });

    item.addEventListener('touchcancel', removeTouchGhost);
});

// ============================================================================
// Zoom Controls
// ============================================================================

document.getElementById('zoomInBtn').addEventListener('click', () => {
    editor.zoom_in();
    updateScrollbars();
});
document.getElementById('zoomOutBtn').addEventListener('click', () => {
    editor.zoom_out();
    updateScrollbars();
});
document.getElementById('zoomResetBtn').addEventListener('click', () => {
    editor.zoom = 1;
    editor.zoom_refresh();
    updateScrollbars();
});

// Pan controls - use Drawflow's internal canvas_x/canvas_y
const panStep = 100;

function panCanvas(dx, dy) {
    // Use Drawflow's internal position
    editor.canvas_x = (editor.canvas_x || 0) + dx;
    editor.canvas_y = (editor.canvas_y || 0) + dy;
    editor.precanvas.style.transform = `translate(${editor.canvas_x}px, ${editor.canvas_y}px) scale(${editor.zoom})`;
}

function getCurrentPan() {
    return {
        x: editor.canvas_x || 0,
        y: editor.canvas_y || 0
    };
}

document.getElementById('panUpBtn').addEventListener('click', () => panCanvas(0, panStep));
document.getElementById('panDownBtn').addEventListener('click', () => panCanvas(0, -panStep));
document.getElementById('panLeftBtn').addEventListener('click', () => panCanvas(panStep, 0));
document.getElementById('panRightBtn').addEventListener('click', () => panCanvas(-panStep, 0));

document.getElementById('panCenterBtn').addEventListener('click', () => {
    editor.canvas_x = 0;
    editor.canvas_y = 0;
    editor.precanvas.style.transform = `translate(0px, 0px) scale(${editor.zoom})`;
    updateScrollbars();
});

// Fit all nodes in view
document.getElementById('fitViewBtn').addEventListener('click', () => {
    const exportData = editor.export();
    const nodes = Object.values(exportData.drawflow.Home.data);

    if (nodes.length === 0) return;

    // Find bounding box of all nodes
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach(node => {
        minX = Math.min(minX, node.pos_x);
        minY = Math.min(minY, node.pos_y);
        maxX = Math.max(maxX, node.pos_x + 250); // Approximate node width
        maxY = Math.max(maxY, node.pos_y + 100); // Approximate node height
    });

    const container = document.getElementById('drawflow');
    const containerWidth = container.clientWidth;
    const containerHeight = container.clientHeight;

    const contentWidth = maxX - minX + 100;
    const contentHeight = maxY - minY + 100;

    // Calculate zoom to fit
    const zoomX = containerWidth / contentWidth;
    const zoomY = containerHeight / contentHeight;
    const newZoom = Math.min(zoomX, zoomY, 1) * 0.9; // Max 1x, with 10% padding

    // Calculate pan to center
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    editor.canvas_x = (containerWidth / 2) - (centerX * newZoom);
    editor.canvas_y = (containerHeight / 2) - (centerY * newZoom);

    editor.zoom = Math.max(0.3, newZoom);
    editor.precanvas.style.transform = `translate(${editor.canvas_x}px, ${editor.canvas_y}px) scale(${editor.zoom})`;
    updateScrollbars();
});
document.getElementById('resetViewBtn').addEventListener('click', () => {
    editor.zoom = 0.85;
    editor.zoom_refresh();
    editor.canvas_x = 0;
    editor.canvas_y = 0;
    editor.precanvas.style.transform = `translate(0px, 0px) scale(${editor.zoom})`;
    updateScrollbars();
});

// Mobile touch handling - sync with Drawflow and prevent conflicts
const drawflowContainer = document.getElementById('drawflow');
let touchStartX = 0;
let touchStartY = 0;
let touchStartPanX = 0;
let touchStartPanY = 0;
let isPanning = false;
let initialPinchDistance = 0;
let initialZoom = 1;

// Track current pan position (mirrors editor.canvas_x/y)
let currentPanX = editor.canvas_x || 0;
let currentPanY = editor.canvas_y || 0;

// Sync our pan variables with Drawflow's internal state
function syncPanFromDrawflow() {
    currentPanX = editor.canvas_x || 0;
    currentPanY = editor.canvas_y || 0;
}

// Single touchstart handler for both pan and pinch
drawflowContainer.addEventListener('touchstart', (e) => {
    syncPanFromDrawflow(); // Always sync first

    if (e.touches.length === 2) {
        e.preventDefault();
        e.stopPropagation();
        isPanning = true;

        // Pan start position
        touchStartX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
        touchStartY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
        touchStartPanX = currentPanX;
        touchStartPanY = currentPanY;

        // Pinch start distance
        initialPinchDistance = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY
        );
        initialZoom = editor.zoom;
    }
}, { passive: false, capture: true });

// Single touchmove handler for both pan and pinch
drawflowContainer.addEventListener('touchmove', (e) => {
    if (isPanning && e.touches.length === 2) {
        e.preventDefault();
        e.stopPropagation();

        // Calculate pan
        const currentX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
        const currentY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
        const deltaX = currentX - touchStartX;
        const deltaY = currentY - touchStartY;
        currentPanX = touchStartPanX + deltaX;
        currentPanY = touchStartPanY + deltaY;

        // Calculate pinch zoom
        if (initialPinchDistance > 0) {
            const currentDistance = Math.hypot(
                e.touches[0].clientX - e.touches[1].clientX,
                e.touches[0].clientY - e.touches[1].clientY
            );
            const scale = currentDistance / initialPinchDistance;
            editor.zoom = Math.min(Math.max(initialZoom * scale, 0.3), 2);
        }

        // Sync with Drawflow's internal state
        editor.canvas_x = currentPanX;
        editor.canvas_y = currentPanY;
        editor.precanvas.style.transform = `translate(${currentPanX}px, ${currentPanY}px) scale(${editor.zoom})`;
        updateScrollbars();
    }
}, { passive: false, capture: true });

drawflowContainer.addEventListener('touchend', (e) => {
    if (isPanning) {
        isPanning = false;
        initialPinchDistance = 0;
    }
}, { capture: true });

// ============================================================================
// Custom Scrollbars
// ============================================================================
const scrollbarH = document.getElementById('scrollbarH');
const scrollbarV = document.getElementById('scrollbarV');
const scrollThumbH = document.getElementById('scrollThumbH');
const scrollThumbV = document.getElementById('scrollThumbV');

// Virtual canvas bounds (expands as nodes are added)
let canvasBounds = { minX: -500, maxX: 1500, minY: -500, maxY: 1500 };

function updateCanvasBounds() {
    const exportData = editor.export();
    const nodes = Object.values(exportData.drawflow.Home.data);

    if (nodes.length === 0) {
        canvasBounds = { minX: -500, maxX: 1500, minY: -500, maxY: 1500 };
        return;
    }

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach(node => {
        minX = Math.min(minX, node.pos_x - 100);
        minY = Math.min(minY, node.pos_y - 100);
        maxX = Math.max(maxX, node.pos_x + 300);
        maxY = Math.max(maxY, node.pos_y + 200);
    });

    // Add padding
    canvasBounds = {
        minX: Math.min(minX - 200, -500),
        maxX: Math.max(maxX + 200, 1500),
        minY: Math.min(minY - 200, -500),
        maxY: Math.max(maxY + 200, 1500)
    };
}

function updateScrollbars() {
    const container = document.getElementById('drawflow');
    const containerWidth = container.clientWidth;
    const containerHeight = container.clientHeight;

    const contentWidth = (canvasBounds.maxX - canvasBounds.minX) * editor.zoom;
    const contentHeight = (canvasBounds.maxY - canvasBounds.minY) * editor.zoom;

    const viewportWidth = containerWidth;
    const viewportHeight = containerHeight;

    // Horizontal scrollbar
    const hTrackWidth = scrollbarH.clientWidth;
    const hThumbWidth = Math.max(40, (viewportWidth / contentWidth) * hTrackWidth);
    const hScrollRange = contentWidth - viewportWidth;
    const hThumbRange = hTrackWidth - hThumbWidth;

    const currentX = editor.canvas_x || 0;
    const scrollXPercent = hScrollRange > 0 ? (-currentX - canvasBounds.minX * editor.zoom) / hScrollRange : 0;
    const hThumbPos = Math.max(0, Math.min(hThumbRange, scrollXPercent * hThumbRange));

    scrollThumbH.style.width = `${hThumbWidth}px`;
    scrollThumbH.style.left = `${hThumbPos}px`;

    // Vertical scrollbar
    const vTrackHeight = scrollbarV.clientHeight;
    const vThumbHeight = Math.max(40, (viewportHeight / contentHeight) * vTrackHeight);
    const vScrollRange = contentHeight - viewportHeight;
    const vThumbRange = vTrackHeight - vThumbHeight;

    const currentY = editor.canvas_y || 0;
    const scrollYPercent = vScrollRange > 0 ? (-currentY - canvasBounds.minY * editor.zoom) / vScrollRange : 0;
    const vThumbPos = Math.max(0, Math.min(vThumbRange, scrollYPercent * vThumbRange));

    scrollThumbV.style.height = `${vThumbHeight}px`;
    scrollThumbV.style.top = `${vThumbPos}px`;
}

// Scrollbar drag handling
let isDraggingScrollbar = false;
let scrollbarDragStart = { x: 0, y: 0, canvasX: 0, canvasY: 0 };
let activeScrollbar = null;

function startScrollbarDrag(e, direction) {
    e.preventDefault();
    isDraggingScrollbar = true;
    activeScrollbar = direction;
    const clientX = e.clientX || e.touches[0].clientX;
    const clientY = e.clientY || e.touches[0].clientY;
    scrollbarDragStart = {
        x: clientX,
        y: clientY,
        canvasX: editor.canvas_x || 0,
        canvasY: editor.canvas_y || 0
    };
    document.addEventListener('mousemove', onScrollbarDrag);
    document.addEventListener('mouseup', stopScrollbarDrag);
    document.addEventListener('touchmove', onScrollbarDrag);
    document.addEventListener('touchend', stopScrollbarDrag);
}

function onScrollbarDrag(e) {
    if (!isDraggingScrollbar) return;

    const clientX = e.clientX || e.touches[0].clientX;
    const clientY = e.clientY || e.touches[0].clientY;

    const container = document.getElementById('drawflow');
    const contentWidth = (canvasBounds.maxX - canvasBounds.minX) * editor.zoom;
    const contentHeight = (canvasBounds.maxY - canvasBounds.minY) * editor.zoom;

    if (activeScrollbar === 'h') {
        const trackWidth = scrollbarH.clientWidth;
        const deltaX = clientX - scrollbarDragStart.x;
        const scrollRatio = deltaX / trackWidth;
        editor.canvas_x = scrollbarDragStart.canvasX - scrollRatio * contentWidth;
    } else {
        const trackHeight = scrollbarV.clientHeight;
        const deltaY = clientY - scrollbarDragStart.y;
        const scrollRatio = deltaY / trackHeight;
        editor.canvas_y = scrollbarDragStart.canvasY - scrollRatio * contentHeight;
    }

    editor.precanvas.style.transform = `translate(${editor.canvas_x}px, ${editor.canvas_y}px) scale(${editor.zoom})`;
    updateScrollbars();
}

function stopScrollbarDrag() {
    isDraggingScrollbar = false;
    activeScrollbar = null;
    document.removeEventListener('mousemove', onScrollbarDrag);
    document.removeEventListener('mouseup', stopScrollbarDrag);
    document.removeEventListener('touchmove', onScrollbarDrag);
    document.removeEventListener('touchend', stopScrollbarDrag);
}

scrollThumbH.addEventListener('mousedown', (e) => startScrollbarDrag(e, 'h'));
scrollThumbH.addEventListener('touchstart', (e) => startScrollbarDrag(e, 'h'));
scrollThumbV.addEventListener('mousedown', (e) => startScrollbarDrag(e, 'v'));
scrollThumbV.addEventListener('touchstart', (e) => startScrollbarDrag(e, 'v'));

// Click on track to jump
scrollbarH.addEventListener('click', (e) => {
    if (e.target === scrollThumbH) return;
    const rect = scrollbarH.getBoundingClientRect();
    const clickPercent = (e.clientX - rect.left) / rect.width;
    const contentWidth = (canvasBounds.maxX - canvasBounds.minX) * editor.zoom;
    editor.canvas_x = -canvasBounds.minX * editor.zoom - clickPercent * contentWidth + drawflowContainer.clientWidth / 2;
    editor.precanvas.style.transform = `translate(${editor.canvas_x}px, ${editor.canvas_y}px) scale(${editor.zoom})`;
    updateScrollbars();
});

scrollbarV.addEventListener('click', (e) => {
    if (e.target === scrollThumbV) return;
    const rect = scrollbarV.getBoundingClientRect();
    const clickPercent = (e.clientY - rect.top) / rect.height;
    const contentHeight = (canvasBounds.maxY - canvasBounds.minY) * editor.zoom;
    editor.canvas_y = -canvasBounds.minY * editor.zoom - clickPercent * contentHeight + drawflowContainer.clientHeight / 2;
    editor.precanvas.style.transform = `translate(${editor.canvas_x}px, ${editor.canvas_y}px) scale(${editor.zoom})`;
    updateScrollbars();
});

// Update scrollbars when panning/zooming
const originalPanCanvas = panCanvas;
panCanvas = function(dx, dy) {
    originalPanCanvas(dx, dy);
    updateScrollbars();
};

// Initial scrollbar setup
updateCanvasBounds();
updateScrollbars();

// Update bounds when nodes change
editor.on('nodeCreated', () => { updateCanvasBounds(); updateScrollbars(); });
editor.on('nodeRemoved', () => { updateCanvasBounds(); updateScrollbars(); });
editor.on('nodeMoved', () => { updateCanvasBounds(); updateScrollbars(); });

// Prevent Drawflow from resetting view on tap on empty canvas
// This happens because Drawflow's click handler can reset transform
const precanvas = editor.precanvas;
precanvas.addEventListener('click', (e) => {
    // If clicking on empty canvas (not on a node), prevent any transform reset
    if (e.target === precanvas || e.target.classList.contains('drawflow')) {
        syncPanFromDrawflow();
    }
});

// Also handle mousedown/up to prevent transform reset on mobile tap
let tapStartTime = 0;
precanvas.addEventListener('mousedown', (e) => {
    tapStartTime = Date.now();
    syncPanFromDrawflow();
});

precanvas.addEventListener('mouseup', (e) => {
    // If it was a quick tap (not a drag), sync the position
    if (Date.now() - tapStartTime < 200) {
        setTimeout(syncPanFromDrawflow, 10);
    }
});

// Mouse wheel for scrolling (Shift+wheel = horizontal, Ctrl+wheel = zoom, wheel = vertical)
drawflowContainer.addEventListener('wheel', (e) => {
    e.preventDefault();

    if (e.ctrlKey || e.metaKey) {
        // Zoom
        if (e.deltaY < 0) {
            editor.zoom_in();
        } else {
            editor.zoom_out();
        }
    } else if (e.shiftKey) {
        // Horizontal scroll
        editor.canvas_x = (editor.canvas_x || 0) - e.deltaY;
        editor.precanvas.style.transform = `translate(${editor.canvas_x}px, ${editor.canvas_y}px) scale(${editor.zoom})`;
    } else {
        // Vertical scroll
        editor.canvas_y = (editor.canvas_y || 0) - e.deltaY;
        editor.precanvas.style.transform = `translate(${editor.canvas_x}px, ${editor.canvas_y}px) scale(${editor.zoom})`;
    }
    updateScrollbars();
}, { passive: false });

// Keyboard navigation (arrow keys to pan when focused)
document.addEventListener('keydown', (e) => {
    // Only if no input is focused
    if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;

    const keyPanStep = 50;
    switch(e.key) {
        case 'ArrowUp':
            panCanvas(0, keyPanStep);
            e.preventDefault();
            break;
        case 'ArrowDown':
            panCanvas(0, -keyPanStep);
            e.preventDefault();
            break;
        case 'ArrowLeft':
            panCanvas(keyPanStep, 0);
            e.preventDefault();
            break;
        case 'ArrowRight':
            panCanvas(-keyPanStep, 0);
            e.preventDefault();
            break;
        case '+':
        case '=':
            editor.zoom_in();
            updateScrollbars();
            break;
        case '-':
            editor.zoom_out();
            updateScrollbars();
            break;
    }
});

// ============================================================================
// Save
// ============================================================================

// Save button handler - will be wrapped by form editor code
document.getElementById('saveFlowBtn').addEventListener('click', function() {
    // Check if we're in form mode (set by form editor code)
    if (typeof currentEditorMode !== 'undefined' && currentEditorMode === 'form') {
        saveFormFlow();
    } else {
        saveFlow();
    }
});

function saveFlow() {
    const exportData = editor.export();
    const nodes = [];

    let order = 0;

    Object.entries(exportData.drawflow.Home.data).forEach(([drawflowId, nodeData]) => {
        if (nodeData.name === 'trigger') return;

        const savedData = nodeDataMap[drawflowId];
        if (!savedData) return;

        const node = {
            id: savedData.dbId || null,
            drawflow_id: drawflowId,  // Send Drawflow ID for mapping new nodes
            order: order++,
            node_type: savedData.type,
            config: { ...savedData.data } || {},
            quick_replies: savedData.data?.quick_replies || [],
            // Save visual position
            pos_x: nodeData.pos_x,
            pos_y: nodeData.pos_y
        };

        // Remove quick_replies from config (it's separate)
        delete node.config.quick_replies;

        // Handle branching from connections
        const outputs = nodeData.outputs;

        // Save next_node_id for regular sequential connections (output_1 -> next node)
        // This applies to non-branching nodes like message_text, message_link, comment_reply
        // For branching nodes, output_1 is handled separately (e.g., follower check true branch)
        const isBranchingNode = ['condition_follower', 'condition_user_interacted', 'message_quick_reply', 'message_button_template'].includes(savedData.type);
        if (!isBranchingNode) {
            if (outputs.output_1?.connections?.length > 0) {
                const targetDrawflowId = outputs.output_1.connections[0].node;
                node.next_node_id = nodeDataMap[targetDrawflowId]?.dbId || `new_${targetDrawflowId}`;
            } else {
                // Explicitly clear connection if removed
                node.next_node_id = null;
            }
        }

        if (savedData.type === 'condition_follower') {
            // output_1 = follower (true), output_2 = not follower (false)
            if (outputs.output_1?.connections?.length > 0) {
                const targetDrawflowId = outputs.output_1.connections[0].node;
                node.config.true_node_id = nodeDataMap[targetDrawflowId]?.dbId || `new_${targetDrawflowId}`;
            } else {
                node.config.true_node_id = null;
            }
            if (outputs.output_2?.connections?.length > 0) {
                const targetDrawflowId = outputs.output_2.connections[0].node;
                node.config.false_node_id = nodeDataMap[targetDrawflowId]?.dbId || `new_${targetDrawflowId}`;
            } else {
                node.config.false_node_id = null;
            }
        }

        if (savedData.type === 'condition_user_interacted') {
            // output_1 = returning user (true), output_2 = new user (false)
            if (outputs.output_1?.connections?.length > 0) {
                const targetDrawflowId = outputs.output_1.connections[0].node;
                node.config.true_node_id = nodeDataMap[targetDrawflowId]?.dbId || `new_${targetDrawflowId}`;
            } else {
                node.config.true_node_id = null;
            }
            if (outputs.output_2?.connections?.length > 0) {
                const targetDrawflowId = outputs.output_2.connections[0].node;
                node.config.false_node_id = nodeDataMap[targetDrawflowId]?.dbId || `new_${targetDrawflowId}`;
            } else {
                node.config.false_node_id = null;
            }
        }

        // Quick reply button branching
        if (savedData.type === 'message_quick_reply') {
            if (node.quick_replies && node.quick_replies.length > 0) {
                node.quick_replies.forEach((qr, i) => {
                    const outputKey = `output_${i + 1}`;
                    if (outputs[outputKey]?.connections?.length > 0) {
                        const targetDrawflowId = outputs[outputKey].connections[0].node;
                        const targetDbId = nodeDataMap[targetDrawflowId]?.dbId;
                        qr.target_node_id = targetDbId || `new_${targetDrawflowId}`;
                    } else {
                        // Explicitly clear connection if removed
                        qr.target_node_id = null;
                    }
                });
            }
        }

        // Button template postback branching
        if (savedData.type === 'message_button_template' && node.config.buttons) {
            // Default type is 'postback' if not specified
            const postbackButtons = node.config.buttons.filter(b => (b.type || 'postback') === 'postback');
            postbackButtons.forEach((btn, i) => {
                const outputKey = `output_${i + 1}`;
                if (outputs[outputKey]?.connections?.length > 0) {
                    const targetDrawflowId = outputs[outputKey].connections[0].node;
                    btn.target_node_id = nodeDataMap[targetDrawflowId]?.dbId || `new_${targetDrawflowId}`;
                } else {
                    // Explicitly clear connection if removed
                    btn.target_node_id = null;
                }
            });
        }

        nodes.push(node);
    });

    // Validate message text lengths before saving
    const validation = validateNodeTextLengths(nodes);
    if (!validation.valid) {
        showToast(validation.error, 'error');
        return;
    }

    // Validate required fields for each node type
    const requiredValidation = validateRequiredFields(nodes);
    if (!requiredValidation.valid) {
        showToast(requiredValidation.error, 'error');
        return;
    }

    // Validate no consecutive message nodes without interaction
    const msgValidation = validateConsecutiveMessages(nodes);
    if (!msgValidation.valid) {
        showToast(msgValidation.error, 'error');
        return;
    }

    // Validate follower check placement (requires prior interaction)
    const followerValidation = validateFollowerCheckPlacement(nodes);
    if (!followerValidation.valid) {
        showToast(followerValidation.error, 'error');
        return;
    }

    // Send to server
    const saveBtn = document.getElementById('saveFlowBtn');
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
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || `HTTP ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            // Check if there are new AI nodes that need configuration
            if (data.ai_config_urls && Object.keys(data.ai_config_urls).length > 0) {
                const aiNodeIds = Object.keys(data.ai_config_urls);
                const firstAiUrl = data.ai_config_urls[aiNodeIds[0]];
                if (confirm('AI Conversation node added! Would you like to configure it now?')) {
                    window.location.href = firstAiUrl;
                    return;
                }
            }
            showToast('Flow saved successfully!', 'success');
            setTimeout(() => location.reload(), 500);
        } else {
            showToast(data.error || 'Failed to save flow', 'error');
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save';
        }
    })
    .catch(error => {
        console.error('Save error:', error);
        showToast('Failed to save: ' + error.message, 'error');
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save';
    });
}

// ============================================================================
// Toast
// ============================================================================

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `alert alert-${type === 'error' ? 'danger' : type === 'success' ? 'success' : 'info'} position-fixed`;
    toast.style.cssText = 'bottom: 20px; right: 20px; z-index: 9999; min-width: 250px;';
    toast.innerHTML = `<i class="bi bi-${type === 'error' ? 'x-circle' : type === 'success' ? 'check-circle' : 'info-circle'} me-2"></i>${message}`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// ============================================================================
// Instagram Message Length Validation
// ============================================================================

const INSTAGRAM_MESSAGE_MAX_LENGTH = 1000;

/**
 * Validate that all text fields in nodes are within Instagram's 1000 char limit.
 * @param {Array} nodes - Array of node objects with config
 * @returns {Object} - { valid: boolean, error: string|null }
 */
function validateNodeTextLengths(nodes) {
    const maxLen = INSTAGRAM_MESSAGE_MAX_LENGTH;

    for (const node of nodes) {
        const config = node.config || {};
        const nodeType = node.node_type || node.type;
        const nodeLabel = nodeType ? nodeType.replace(/_/g, ' ') : 'Unknown';

        // Check main text field
        if (config.text && config.text.length > maxLen) {
            return {
                valid: false,
                error: `Message text in "${nodeLabel}" exceeds ${maxLen} characters (${config.text.length} chars). Please shorten the message.`
            };
        }

        // Check text variations
        if (config.variations && Array.isArray(config.variations)) {
            for (let i = 0; i < config.variations.length; i++) {
                const variation = config.variations[i];
                if (variation && variation.length > maxLen) {
                    return {
                        valid: false,
                        error: `Text variation ${i + 1} in "${nodeLabel}" exceeds ${maxLen} characters (${variation.length} chars). Please shorten the message.`
                    };
                }
            }
        }

        // Check prompt_text for collect_data nodes
        if (config.prompt_text && config.prompt_text.length > maxLen) {
            return {
                valid: false,
                error: `Prompt text in "${nodeLabel}" exceeds ${maxLen} characters (${config.prompt_text.length} chars). Please shorten the message.`
            };
        }
    }

    return { valid: true, error: null };
}

/**
 * Validate that required fields are filled for each node type.
 * @param {Array} nodes - Array of node objects with config
 * @returns {Object} - { valid: boolean, error: string|null }
 */
function validateRequiredFields(nodes) {
    for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i];
        const config = node.config || {};
        const nodeType = node.node_type || node.type;
        const nodeNum = i + 1;

        switch (nodeType) {
            case 'message_text':
                if (!config.text || !config.text.trim()) {
                    return {
                        valid: false,
                        error: `Step ${nodeNum} (Text Message): Message text is required.`
                    };
                }
                break;

            case 'message_link':
                if (!config.text || !config.text.trim()) {
                    return {
                        valid: false,
                        error: `Step ${nodeNum} (Link Message): Message text is required.`
                    };
                }
                if (!config.url || !config.url.trim()) {
                    return {
                        valid: false,
                        error: `Step ${nodeNum} (Link Message): URL is required.`
                    };
                }
                break;

            case 'message_button_template':
                if (!config.text || !config.text.trim()) {
                    return {
                        valid: false,
                        error: `Step ${nodeNum} (Button Template): Message text is required.`
                    };
                }
                if (!config.buttons || config.buttons.length === 0) {
                    return {
                        valid: false,
                        error: `Step ${nodeNum} (Button Template): At least one button is required.`
                    };
                }
                // Validate each button has title and action
                for (let j = 0; j < config.buttons.length; j++) {
                    const btn = config.buttons[j];
                    if (!btn.title || !btn.title.trim()) {
                        return {
                            valid: false,
                            error: `Step ${nodeNum} (Button Template): Button ${j + 1} title is required.`
                        };
                    }
                    const btnType = btn.type || 'postback';
                    if (btnType === 'web_url' && (!btn.url || !btn.url.trim())) {
                        return {
                            valid: false,
                            error: `Step ${nodeNum} (Button Template): Button ${j + 1} URL is required for URL buttons.`
                        };
                    }
                }
                break;

            case 'message_quick_reply':
                if (!config.text || !config.text.trim()) {
                    return {
                        valid: false,
                        error: `Step ${nodeNum} (Quick Reply): Message text is required.`
                    };
                }
                // Quick replies are stored in node.quick_replies, not config
                const quickReplies = node.quick_replies || [];
                if (quickReplies.length === 0) {
                    return {
                        valid: false,
                        error: `Step ${nodeNum} (Quick Reply): At least one quick reply button is required.`
                    };
                }
                // Validate each quick reply has a title
                for (let j = 0; j < quickReplies.length; j++) {
                    const qr = quickReplies[j];
                    if (!qr.title || !qr.title.trim()) {
                        return {
                            valid: false,
                            error: `Step ${nodeNum} (Quick Reply): Button ${j + 1} title is required.`
                        };
                    }
                }
                break;

            case 'comment_reply':
                if (!config.text || !config.text.trim()) {
                    return {
                        valid: false,
                        error: `Step ${nodeNum} (Comment Reply): Reply text is required.`
                    };
                }
                break;

            case 'collect_data':
                if (!config.prompt_text || !config.prompt_text.trim()) {
                    return {
                        valid: false,
                        error: `Step ${nodeNum} (Collect Data): Prompt text is required.`
                    };
                }
                break;
        }
    }

    return { valid: true, error: null };
}

/**
 * Validate that flow doesn't have consecutive message nodes without user interaction.
 * Instagram only allows ONE message to non-followers until they reply.
 *
 * RULE: Before any interaction node, only ONE message is allowed.
 *       After an interaction node (user clicked/responded), multiple messages are allowed.
 *
 * @param {Array} nodes - Array of node objects
 * @returns {Object} - { valid: boolean, error: string|null }
 */
function validateConsecutiveMessages(nodes) {
    // Node types that send a DM and DON'T wait for interaction
    const fireAndForgetTypes = ['message_text', 'message_link'];

    // ALL node types that send a DM
    const allDmTypes = ['message_text', 'message_link', 'message_quick_reply', 'message_button_template', 'collect_data'];

    // Node types that trigger user interaction (clicking button, typing response)
    const interactionTypes = ['message_quick_reply', 'message_button_template', 'collect_data'];

    // Build node lookup and reverse graph (who points to each node)
    const nodeMap = {};  // id -> { type, node, id }
    const reverseGraph = {};  // nodeId -> [parentNodeIds]

    // Helper to get canonical ID for a node
    function getNodeId(node) {
        return node.id || node.temp_id || (node.drawflow_id ? `new_${node.drawflow_id}` : null);
    }

    // Build node map
    nodes.forEach(node => {
        const nodeType = node.node_type || node.type;
        const id = getNodeId(node);
        if (id) {
            nodeMap[id] = { type: nodeType, node, id };
            reverseGraph[id] = [];
        }
        // Also map by drawflow_id for lookups
        if (node.drawflow_id) {
            nodeMap[node.drawflow_id] = { type: nodeType, node, id };
            nodeMap[`new_${node.drawflow_id}`] = { type: nodeType, node, id };
        }
    });

    // Build reverse graph (parent -> child connections)
    nodes.forEach(node => {
        const parentId = getNodeId(node);

        // next_node_id connection
        if (node.next_node_id && nodeMap[node.next_node_id]) {
            const childId = nodeMap[node.next_node_id].id;
            if (childId && reverseGraph[childId]) {
                reverseGraph[childId].push(parentId);
            }
        }

        // Quick reply button connections
        if (node.quick_replies) {
            node.quick_replies.forEach(qr => {
                if (qr.target_node_id && nodeMap[qr.target_node_id]) {
                    const childId = nodeMap[qr.target_node_id].id;
                    if (childId && reverseGraph[childId]) {
                        reverseGraph[childId].push(parentId);
                    }
                }
            });
        }

        // Condition node branches
        const config = node.config || {};
        if (config.true_node_id && nodeMap[config.true_node_id]) {
            const childId = nodeMap[config.true_node_id].id;
            if (childId && reverseGraph[childId]) {
                reverseGraph[childId].push(parentId);
            }
        }
        if (config.false_node_id && nodeMap[config.false_node_id]) {
            const childId = nodeMap[config.false_node_id].id;
            if (childId && reverseGraph[childId]) {
                reverseGraph[childId].push(parentId);
            }
        }

        // Button template postback connections
        if (config.buttons) {
            config.buttons.forEach(btn => {
                if (btn.target_node_id && nodeMap[btn.target_node_id]) {
                    const childId = nodeMap[btn.target_node_id].id;
                    if (childId && reverseGraph[childId]) {
                        reverseGraph[childId].push(parentId);
                    }
                }
            });
        }
    });

    // Check if an interaction node exists upstream of a given node
    function hasInteractionUpstream(nodeId, visited = new Set()) {
        if (!nodeId || visited.has(nodeId)) return false;
        visited.add(nodeId);

        const parents = reverseGraph[nodeId] || [];
        for (const parentId of parents) {
            const parentInfo = nodeMap[parentId];
            if (!parentInfo) continue;

            // If parent is an interaction node, return true
            if (interactionTypes.includes(parentInfo.type)) {
                return true;
            }

            // Recursively check parent's ancestors
            if (hasInteractionUpstream(parentId, visited)) {
                return true;
            }
        }

        return false;
    }

    // Check each fire-and-forget node
    for (const node of nodes) {
        const nodeType = node.node_type || node.type;
        if (!fireAndForgetTypes.includes(nodeType)) continue;

        const nodeId = getNodeId(node);

        // Check next_node_id connection
        if (node.next_node_id) {
            const nextInfo = nodeMap[node.next_node_id];
            if (nextInfo && allDmTypes.includes(nextInfo.type)) {
                // This is a fire-and-forget node pointing to another DM node
                // Only invalid if NO interaction node is upstream of this node
                if (!hasInteractionUpstream(nodeId)) {
                    const currentLabel = nodeType.replace(/_/g, ' ');
                    const nextLabel = nextInfo.type.replace(/_/g, ' ');
                    return {
                        valid: false,
                        error: `Cannot have "${currentLabel}" followed by "${nextLabel}" before user interaction. Instagram only allows one message to non-followers until they reply. Use Quick Reply or Button Template as your first message instead.`
                    };
                }
            }
        }
    }

    return { valid: true, error: null };
}

/**
 * Validate that Follower Check nodes only appear after user interaction.
 * Instagram requires user consent (interaction) before we can check follower status.
 *
 * @param {Array} nodes - Array of node objects
 * @returns {Object} - { valid: boolean, error: string|null }
 */
function validateFollowerCheckPlacement(nodes) {
    // Nodes that DON'T trigger user interaction
    const nonInteractionTypes = ['comment_reply', 'message_text', 'message_link'];

    // Nodes that DO trigger user interaction (user must click/respond)
    const interactionTypes = ['message_quick_reply', 'message_button_template', 'collect_data'];

    // Build lookup maps
    const nodeById = {};
    nodes.forEach(node => {
        const nodeType = node.node_type || node.type;
        const nodeInfo = { type: nodeType, node };

        if (node.id) nodeById[node.id] = nodeInfo;
        if (node.drawflow_id) {
            nodeById[node.drawflow_id] = nodeInfo;
            nodeById[`new_${node.drawflow_id}`] = nodeInfo;
        }
        if (node.temp_id) nodeById[node.temp_id] = nodeInfo;
    });

    // Helper to get node type by ID
    function getNodeType(nodeId) {
        if (!nodeId) return null;
        const info = nodeById[nodeId];
        return info ? info.type : null;
    }

    // Check if flow has any follower check nodes
    const hasFollowerCheck = nodes.some(n => (n.node_type || n.type) === 'condition_follower');
    if (!hasFollowerCheck) {
        return { valid: true, error: null };
    }

    // Check if flow has any interaction nodes
    const hasInteractionNode = nodes.some(n => interactionTypes.includes(n.node_type || n.type));
    if (!hasInteractionNode) {
        return {
            valid: false,
            error: 'Follower Check requires a Quick Reply, Button Template, or Collect Data step first. The user must interact (click a button or respond) before we can check their follower status.'
        };
    }

    // Check that no non-interaction node directly points to follower check
    for (const node of nodes) {
        const nodeType = node.node_type || node.type;

        // Check non-interaction nodes' next_node_id
        if (nonInteractionTypes.includes(nodeType)) {
            const nextType = getNodeType(node.next_node_id);
            if (nextType === 'condition_follower') {
                const nodeLabel = nodeType.replace(/_/g, ' ');
                return {
                    valid: false,
                    error: `Cannot have "${nodeLabel}" directly followed by Follower Check. The user must interact first (click a Quick Reply or Button) before we can check their follower status.`
                };
            }
        }

        // Check condition nodes' branches
        if (nodeType === 'condition_user_interacted') {
            const config = node.config || {};
            const trueType = getNodeType(config.true_node_id);
            const falseType = getNodeType(config.false_node_id);
            if (trueType === 'condition_follower' || falseType === 'condition_follower') {
                return {
                    valid: false,
                    error: 'Cannot have Returning User Check directly branch to Follower Check. The user must interact first (click a Quick Reply or Button) before we can check their follower status.'
                };
            }
        }
    }

    return { valid: true, error: null };
}

// ============================================================================
// Form Editor (Complete Rewrite - Clean Design)
// ============================================================================

let formNodes = [];
let currentEditorMode = 'visual';
let formNodeIdCounter = 1;

const NODE_TYPES = {
    'comment_reply': {
        icon: 'bi-chat-dots',
        class: 'comment-reply',
        title: 'Reply to Comment',
        description: 'Automatically reply when someone comments on your post'
    },
    'message_text': {
        icon: 'bi-chat-left-text',
        class: 'text-message',
        title: 'Send Message',
        description: 'Send a text message to the user'
    },
    'message_quick_reply': {
        icon: 'bi-ui-radios-grid',
        class: 'quick-reply',
        title: 'Quick Reply',
        description: 'Show buttons for the user to choose from'
    },
    'message_button_template': {
        icon: 'bi-menu-button-wide',
        class: 'button-template',
        title: 'Message with Buttons',
        description: 'Send a message with clickable action buttons'
    },
    'message_link': {
        icon: 'bi-link',
        class: 'link-message',
        title: 'Send Link',
        description: 'Send a message with a clickable link'
    },
    'condition_follower': {
        icon: 'bi-person-check',
        class: 'follower-check',
        title: 'Check if Follower',
        description: 'Do different things based on whether user follows you'
    },
    'condition_user_interacted': {
        icon: 'bi-person-lines-fill',
        class: 'user-interacted',
        title: 'Check if Returning',
        description: 'Do different things for new vs returning users'
    },
    'collect_data': {
        icon: 'bi-input-cursor-text',
        class: 'collect-data',
        title: 'Collect Info',
        description: 'Ask user for their email, name, phone, etc.'
    },
    'ai_conversation': {
        icon: 'bi-cpu',
        class: 'ai-conversation',
        title: 'AI Chat',
        description: 'Let AI handle the conversation automatically'
    }
};

// Initialize form nodes from database (existingNodes)
function initFormNodesFromDB() {
    formNodes = [];

    // Get current positions from Drawflow (if Visual Editor has been used)
    const drawflowPositions = {};
    try {
        const exportData = editor.export();
        Object.entries(exportData.drawflow.Home.data).forEach(([drawflowId, nodeData]) => {
            const savedData = nodeDataMap[drawflowId];
            if (savedData?.dbId) {
                drawflowPositions[savedData.dbId] = {
                    x: nodeData.pos_x,
                    y: nodeData.pos_y
                };
            }
        });
    } catch (e) {
        // Editor may not be initialized yet
    }

    // Sort by order from database
    const sorted = [...existingNodes].sort((a, b) => a.order - b.order);

    sorted.forEach((dbNode) => {
        // Prefer Drawflow positions (current), fall back to existingNodes (page load)
        const currentPos = drawflowPositions[dbNode.id];
        const pos_x = currentPos?.x ?? dbNode.config?._pos_x;
        const pos_y = currentPos?.y ?? dbNode.config?._pos_y;

        const node = {
            tempId: `node_${formNodeIdCounter++}`,
            dbId: dbNode.id,
            type: dbNode.node_type,
            config: { ...dbNode.config },
            quickReplies: (dbNode.quick_replies || []).map(qr => ({
                title: qr.title || '',
                payload: qr.payload || '',
                targetNodeId: qr.target_node_id  // DB ID of target
            })),
            nextNodeId: dbNode.next_node_id,  // DB ID of next node
            // Preserve visual editor positions (from Drawflow or existingNodes)
            _pos_x: pos_x,
            _pos_y: pos_y
        };

        // Remove internal position fields from config display (but keep in node._pos_x/_pos_y)
        delete node.config._pos_x;
        delete node.config._pos_y;
        delete node.config.quick_replies;

        formNodes.push(node);
    });

    // Sequential fallback: if node has no explicit nextNodeId and is not a branching type,
    // connect it to the next node in order (same logic as Visual Editor)
    const branchingTypes = ['condition_follower', 'condition_user_interacted', 'message_quick_reply', 'message_button_template'];

    // Collect all branch target IDs
    const branchTargetIds = new Set();
    formNodes.forEach(node => {
        if (node.type === 'condition_follower' || node.type === 'condition_user_interacted') {
            if (node.config.true_node_id) branchTargetIds.add(node.config.true_node_id);
            if (node.config.false_node_id) branchTargetIds.add(node.config.false_node_id);
        }
        if (node.type === 'message_quick_reply' && node.quickReplies) {
            node.quickReplies.forEach(qr => {
                if (qr.targetNodeId) branchTargetIds.add(qr.targetNodeId);
            });
        }
        if (node.type === 'message_button_template' && node.config?.buttons) {
            node.config.buttons.forEach(btn => {
                if (btn.target_node_id) branchTargetIds.add(btn.target_node_id);
            });
        }
        if (node.nextNodeId) branchTargetIds.add(node.nextNodeId);
    });

    formNodes.forEach((node, i) => {
        // Skip if already has explicit nextNodeId
        if (node.nextNodeId) return;
        // Skip branching nodes
        if (branchingTypes.includes(node.type)) return;
        // Skip if this node is a branch target (don't chain sequentially)
        if (branchTargetIds.has(node.dbId)) return;

        // Connect to next node in order
        const nextNode = formNodes[i + 1];
        if (nextNode) {
            node.nextNodeId = nextNode.dbId;
        }
    });
}

// Check if mobile device
const isMobileDevice = () => {
    return window.innerWidth <= 767 || ('ontouchstart' in window && navigator.maxTouchPoints > 0);
};

// Switch to a specific editor mode
function switchEditorMode(mode) {
    if (mode === currentEditorMode) return;

    document.querySelectorAll('#editorModeToggle button').forEach(b => b.classList.remove('active'));
    document.querySelector(`#editorModeToggle button[data-mode="${mode}"]`).classList.add('active');

    if (mode === 'visual') {
        document.getElementById('visualEditor').classList.remove('hidden');
        document.getElementById('formEditor').classList.remove('active');
        document.getElementById('resetViewBtn').style.display = '';
        document.body.classList.remove('form-editor-active');
    } else {
        document.getElementById('visualEditor').classList.add('hidden');
        document.getElementById('formEditor').classList.add('active');
        document.getElementById('resetViewBtn').style.display = 'none';
        document.body.classList.add('form-editor-active');
        // Load fresh from database each time
        initFormNodesFromDB();
        renderFormEditor();
        attachFormEventHandlers();
    }

    currentEditorMode = mode;
}

// Mode toggle (desktop)
document.querySelectorAll('#editorModeToggle button').forEach(btn => {
    btn.addEventListener('click', function() {
        switchEditorMode(this.dataset.mode);
    });
});

// Mobile "Switch Editor" button → opens editor choice modal
function showEditorChoiceModal(showVisualNotice) {
    let overlay = document.getElementById('editorChoiceOverlay');
    if (overlay) {
        // Reset to choices view
        overlay.querySelector('#ecChoicesView').style.display = '';
        overlay.querySelector('#ecVisualNotice').style.display = 'none';
        if (showVisualNotice) {
            overlay.querySelector('#ecChoicesView').style.display = 'none';
            overlay.querySelector('#ecVisualNotice').style.display = '';
        }
        overlay.classList.add('active');
        return;
    }

    overlay = document.createElement('div');
    overlay.id = 'editorChoiceOverlay';
    overlay.className = 'visual-desktop-overlay active';
    overlay.innerHTML = `
        <div class="visual-desktop-modal">
            <div class="visual-desktop-modal-header">
                <h3>Choose Editor</h3>
                <button class="visual-desktop-close" id="ecClose">&times;</button>
            </div>

            <div id="ecChoicesView" style="${showVisualNotice ? 'display:none' : ''}">
                <p style="font-size:13px; color:#6b7280; margin-bottom:14px;">Switch to a different editor mode:</p>
                <div class="ec-options">
                    <button class="ec-option" id="ecOptWizard">
                        <div class="ec-option-icon" style="background:var(--primary, #7c3aed);">
                            <i class="bi bi-magic"></i>
                        </div>
                        <div class="ec-option-info">
                            <div class="ec-option-title">Easy Editor</div>
                            <div class="ec-option-desc">Guided step-by-step, best for mobile</div>
                        </div>
                        <i class="bi bi-chevron-right" style="color:#9ca3af;"></i>
                    </button>
                    <button class="ec-option" id="ecOptForm">
                        <div class="ec-option-icon" style="background:#0d6efd;">
                            <i class="bi bi-list-ul"></i>
                        </div>
                        <div class="ec-option-info">
                            <div class="ec-option-title">Form Editor</div>
                            <div class="ec-option-desc">Edit all fields, connections, add/remove steps</div>
                        </div>
                        <i class="bi bi-chevron-right" style="color:#9ca3af;"></i>
                    </button>
                    <button class="ec-option" id="ecOptVisual">
                        <div class="ec-option-icon" style="background:#7c3aed;">
                            <i class="bi bi-diagram-3"></i>
                        </div>
                        <div class="ec-option-info">
                            <div class="ec-option-title">Visual Editor</div>
                            <div class="ec-option-desc">Drag-and-drop flow builder with canvas</div>
                        </div>
                        <i class="bi bi-chevron-right" style="color:#9ca3af;"></i>
                    </button>
                </div>
            </div>

            <div id="ecVisualNotice" style="${showVisualNotice ? '' : 'display:none'}">
                <div class="visual-desktop-demo">
                    <div class="visual-desktop-demo-inner">
                        <div class="vd-node vd-node-1"><i class="bi bi-chat-dots"></i> Reply</div>
                        <svg width="60" height="24" style="display:block; margin:0 auto;"><path d="M30,0 C30,12 30,12 30,24" stroke="#7c3aed" stroke-width="2" fill="none" opacity="0.4"/></svg>
                        <div class="vd-node vd-node-2"><i class="bi bi-link"></i> Link</div>
                        <svg width="60" height="24" style="display:block; margin:0 auto;"><path d="M30,0 C30,12 30,12 30,24" stroke="#7c3aed" stroke-width="2" fill="none" opacity="0.4"/></svg>
                        <div class="vd-node vd-node-3"><i class="bi bi-person-check"></i> Check</div>
                    </div>
                    <div class="vd-cursor"><i class="bi bi-cursor-fill"></i></div>
                </div>
                <div class="visual-desktop-notice">
                    <i class="bi bi-display"></i>
                    <h4>Desktop Only</h4>
                    <p>The drag-and-drop canvas needs a larger screen. Open this flow on your computer to use it.</p>
                </div>
                <div class="visual-desktop-btns">
                    <button class="vd-btn vd-btn-wizard" id="ecNoticeBtnWizard">
                        <i class="bi bi-magic me-1"></i>Easy Editor
                    </button>
                    <button class="vd-btn vd-btn-form" id="ecNoticeBtnForm">
                        <i class="bi bi-list-ul me-1"></i>Stay in Form
                    </button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    function closeModal() { overlay.classList.remove('active'); }

    document.getElementById('ecClose').addEventListener('click', closeModal);
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) closeModal();
    });

    // Easy Editor
    document.getElementById('ecOptWizard').addEventListener('click', function() {
        if (typeof wizardUrl !== 'undefined' && wizardUrl) {
            window.location.href = wizardUrl;
        }
    });

    // Form Editor — already in form mode, just close
    document.getElementById('ecOptForm').addEventListener('click', function() {
        closeModal();
        if (currentEditorMode !== 'form') switchEditorMode('form');
    });

    // Visual Editor — show desktop-only notice on mobile
    document.getElementById('ecOptVisual').addEventListener('click', function() {
        if (isMobileDevice()) {
            overlay.querySelector('#ecChoicesView').style.display = 'none';
            overlay.querySelector('#ecVisualNotice').style.display = '';
        } else {
            closeModal();
            switchEditorMode('visual');
        }
    });

    // Fallback buttons from visual notice
    document.getElementById('ecNoticeBtnWizard').addEventListener('click', function() {
        if (typeof wizardUrl !== 'undefined' && wizardUrl) {
            window.location.href = wizardUrl;
        }
    });
    document.getElementById('ecNoticeBtnForm').addEventListener('click', function() {
        closeModal();
        if (currentEditorMode !== 'form') switchEditorMode('form');
    });
}

// Mobile switch editor button
const _mobileSwitchBtn = document.getElementById('mobileSwitchEditorBtn');
if (_mobileSwitchBtn) {
    _mobileSwitchBtn.addEventListener('click', function() {
        showEditorChoiceModal(false);
    });
}

// Auto-switch to Wizard editor on mobile devices
let _redirectingToWizard = false;
const _urlParams = new URLSearchParams(window.location.search);
const _forceMode = _urlParams.get('mode');

if (_forceMode === 'form' && isMobileDevice()) {
    // Explicitly requested form mode — don't redirect to wizard
    setTimeout(() => { switchEditorMode('form'); }, 500);
} else if (isMobileDevice() && typeof wizardUrl !== 'undefined' && wizardUrl) {
    _redirectingToWizard = true;
    window.location.href = wizardUrl;
} else if (isMobileDevice()) {
    setTimeout(() => {
        if (!_redirectingToWizard) switchEditorMode('form');
    }, 500);
}

// Render the form editor UI
function renderFormEditor() {
    const container = document.getElementById('formNodesContainer');
    container.innerHTML = '';

    if (formNodes.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="bi bi-chat-dots fs-1 mb-2 d-block"></i>
                <p class="mb-1">Your automation flow is empty</p>
                <p class="small">Click "Add Step" below to start building your flow</p>
            </div>
        `;
        return;
    }

    // Analyze flow structure
    const connections = analyzeFlowConnections();

    formNodes.forEach((node, index) => {
        const typeInfo = NODE_TYPES[node.type] || { icon: 'bi-question', class: 'unknown', title: 'Unknown' };
        container.insertAdjacentHTML('beforeend', buildNodeCard(node, index, typeInfo, connections));
    });
}

// Flag to track if form event handlers have been attached
let formEventHandlersAttached = false;

// Analyze flow structure to find what connects to each node
function analyzeFlowConnections() {
    const connections = {}; // nodeId -> [{from: nodeId, type: 'next'|'follower'|'not_follower'|'button:X'|'qr:X'}]

    formNodes.forEach((node, idx) => {
        const nodeId = node.dbId || node.tempId;

        // Check explicit nextNodeId for all node types
        if (node.nextNodeId) {
            if (!connections[node.nextNodeId]) connections[node.nextNodeId] = [];
            connections[node.nextNodeId].push({ from: nodeId, fromIndex: idx, type: 'next' });
        }

        // Follower check branches
        if (node.type === 'condition_follower') {
            if (node.config.true_node_id) {
                const targetId = node.config.true_node_id;
                if (!connections[targetId]) connections[targetId] = [];
                connections[targetId].push({ from: nodeId, fromIndex: idx, type: 'follower' });
            }
            if (node.config.false_node_id) {
                const targetId = node.config.false_node_id;
                if (!connections[targetId]) connections[targetId] = [];
                connections[targetId].push({ from: nodeId, fromIndex: idx, type: 'not_follower' });
            }
        }

        // Returning user check branches
        if (node.type === 'condition_user_interacted') {
            if (node.config.true_node_id) {
                const targetId = node.config.true_node_id;
                if (!connections[targetId]) connections[targetId] = [];
                connections[targetId].push({ from: nodeId, fromIndex: idx, type: 'returning_user' });
            }
            if (node.config.false_node_id) {
                const targetId = node.config.false_node_id;
                if (!connections[targetId]) connections[targetId] = [];
                connections[targetId].push({ from: nodeId, fromIndex: idx, type: 'new_user' });
            }
        }

        // Quick reply buttons
        if (node.type === 'message_quick_reply' && node.quickReplies) {
            node.quickReplies.forEach((qr, i) => {
                if (qr.targetNodeId) {
                    if (!connections[qr.targetNodeId]) connections[qr.targetNodeId] = [];
                    connections[qr.targetNodeId].push({ from: nodeId, fromIndex: idx, type: 'qr', label: qr.title || `Button ${i+1}` });
                }
            });
        }

        // Button template
        if (node.type === 'message_button_template' && node.config.buttons) {
            node.config.buttons.forEach((btn, i) => {
                if (btn.target_node_id && (btn.type || 'postback') === 'postback') {
                    if (!connections[btn.target_node_id]) connections[btn.target_node_id] = [];
                    connections[btn.target_node_id].push({ from: nodeId, fromIndex: idx, type: 'button', label: btn.title || `Button ${i+1}` });
                }
            });
        }
    });

    return connections;
}

// Build "connected from" badges HTML
function buildConnectionBadges(node, index, connections) {
    const nodeId = node.dbId || node.tempId;
    const incomingConnections = connections[nodeId] || [];

    if (index === 0 && incomingConnections.length === 0) {
        return '<span class="badge bg-warning text-dark"><i class="bi bi-lightning-charge me-1"></i>Starts when triggered</span>';
    }

    if (incomingConnections.length === 0) {
        return '<span class="badge bg-secondary"><i class="bi bi-question-circle me-1"></i>Not connected yet</span>';
    }

    return incomingConnections.map(conn => {
        const fromNode = formNodes[conn.fromIndex];
        const fromInfo = NODE_TYPES[fromNode?.type] || { title: 'Unknown' };
        const stepNum = conn.fromIndex + 1;

        switch (conn.type) {
            case 'next':
                return `<span class="badge bg-primary"><i class="bi bi-arrow-right me-1"></i>After Step ${stepNum}</span>`;
            case 'follower':
                return `<span class="badge bg-success"><i class="bi bi-person-check me-1"></i>When follower (Step ${stepNum})</span>`;
            case 'not_follower':
                return `<span class="badge bg-danger"><i class="bi bi-person-x me-1"></i>When not follower (Step ${stepNum})</span>`;
            case 'returning_user':
                return `<span class="badge bg-success"><i class="bi bi-arrow-repeat me-1"></i>When returning (Step ${stepNum})</span>`;
            case 'new_user':
                return `<span class="badge bg-info"><i class="bi bi-person-plus me-1"></i>When first time (Step ${stepNum})</span>`;
            case 'qr':
                return `<span class="badge bg-info"><i class="bi bi-hand-index me-1"></i>When user taps "${conn.label}"</span>`;
            case 'button':
                return `<span class="badge bg-purple text-white"><i class="bi bi-hand-index me-1"></i>When user taps "${conn.label}"</span>`;
            default:
                return `<span class="badge bg-secondary">After Step ${stepNum}</span>`;
        }
    }).join(' ');
}

// Build HTML for a single node card
function buildNodeCard(node, index, typeInfo, connections) {
    const connectionBadges = buildConnectionBadges(node, index, connections);

    let bodyHtml = buildNodeFields(node, index);

    return `
        <div class="form-node-card" data-node-index="${index}" data-temp-id="${node.tempId}">
            <div class="form-node-header">
                <div class="node-icon ${typeInfo.class}">
                    <i class="bi ${typeInfo.icon}"></i>
                </div>
                <div class="node-title">
                    <span>Step ${index + 1}: ${typeInfo.title}</span>
                    <small class="d-block text-muted" style="font-size: 11px;">${typeInfo.description || ''}</small>
                    <div class="node-connections mt-1">${connectionBadges}</div>
                </div>
                <div class="node-actions">
                    <button type="button" class="delete-node-btn danger" title="Delete this step">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
            <div class="form-node-body">
                ${bodyHtml}
            </div>
        </div>
    `;
}

// Build form fields based on node type
function buildNodeFields(node, index) {
    let html = '';

    switch (node.type) {
        case 'comment_reply':
            html = `
                <div class="mb-3">
                    <label class="form-label">What to reply</label>
                    <textarea class="form-control node-field" data-field="text" rows="2" placeholder="e.g., Thanks for commenting! Check your DMs 📩">${escapeHtml(node.config.text || '')}</textarea>
                    <small class="text-muted">Public reply on their comment</small>
                </div>
                ${buildVariationsSection(node, index)}
                <div class="form-node-connection next-node">
                    <div class="connection-label"><i class="bi bi-arrow-right-circle text-primary me-1"></i>What happens next?</div>
                    <select class="form-select form-select-sm next-node-select">
                        ${buildTargetOptions(node.nextNodeId, index)}
                    </select>
                </div>
            `;
            break;

        case 'message_text':
            html = `
                <div class="mb-3">
                    <label class="form-label">Your message</label>
                    <textarea class="form-control node-field" data-field="text" rows="2" placeholder="Type your message here...">${escapeHtml(node.config.text || '')}</textarea>
                </div>
                ${buildVariationsSection(node, index)}
                <div class="form-node-connection next-node">
                    <div class="connection-label"><i class="bi bi-arrow-right-circle text-primary me-1"></i>What happens next?</div>
                    <select class="form-select form-select-sm next-node-select">
                        ${buildTargetOptions(node.nextNodeId, index)}
                    </select>
                </div>
            `;
            break;

        case 'message_link':
            html = `
                <div class="mb-3">
                    <label class="form-label">Your message</label>
                    <textarea class="form-control node-field" data-field="text" rows="2" placeholder="e.g., Here's your link! 🎉">${escapeHtml(node.config.text || '')}</textarea>
                </div>
                ${buildVariationsSection(node, index)}
                <div class="mb-3">
                    <label class="form-label">Link URL</label>
                    <input type="url" class="form-control node-field" data-field="url" value="${escapeHtml(node.config.url || '')}" placeholder="https://your-link.com">
                    <small class="text-muted">Link sent to user</small>
                </div>
                <div class="form-node-connection next-node">
                    <div class="connection-label"><i class="bi bi-arrow-right-circle text-primary me-1"></i>What happens next?</div>
                    <select class="form-select form-select-sm next-node-select">
                        ${buildTargetOptions(node.nextNodeId, index)}
                    </select>
                </div>
            `;
            break;

        case 'message_quick_reply':
            let qrHtml = '';
            (node.quickReplies || []).forEach((qr, i) => {
                qrHtml += `
                    <div class="form-node-connection button-branch mb-2" data-qr-index="${i}">
                        <div class="d-flex gap-2 mb-2">
                            <input type="text" class="form-control form-control-sm qr-title" value="${escapeHtml(qr.title || '')}" placeholder="Button text (e.g., Yes!)" maxlength="20">
                            <button type="button" class="btn btn-outline-danger btn-sm remove-qr" title="Remove this button"><i class="bi bi-x"></i></button>
                        </div>
                        <div class="d-flex align-items-center gap-2">
                            <small class="text-muted">When tapped:</small>
                            <select class="form-select form-select-sm qr-target">
                                ${buildTargetOptions(qr.targetNodeId, index)}
                            </select>
                        </div>
                    </div>
                `;
            });
            html = `
                <div class="mb-3">
                    <label class="form-label">Your question or message</label>
                    <textarea class="form-control node-field" data-field="text" rows="2" placeholder="e.g., What would you like to do?">${escapeHtml(node.config.text || '')}</textarea>
                </div>
                ${buildVariationsSection(node, index)}
                <label class="form-label">Answer buttons</label>
                <small class="text-muted d-block mb-2">User taps to continue</small>
                <div class="qr-container">${qrHtml}</div>
                <button type="button" class="btn btn-outline-primary btn-sm add-qr mt-2"><i class="bi bi-plus me-1"></i>Add Answer Button</button>
            `;
            break;

        case 'message_button_template':
            let btnHtml = '';
            (node.config.buttons || []).forEach((btn, i) => {
                const isUrl = btn.type === 'web_url';
                btnHtml += `
                    <div class="form-node-connection button-branch mb-2" data-btn-index="${i}">
                        <div class="btn-row-flex mb-2">
                            <select class="form-select form-select-sm btn-type" title="Button type">
                                <option value="postback" ${!isUrl ? 'selected' : ''}>Action</option>
                                <option value="web_url" ${isUrl ? 'selected' : ''}>Open Link</option>
                            </select>
                            <input type="text" class="form-control form-control-sm btn-title" value="${escapeHtml(btn.title || '')}" placeholder="Button text" maxlength="20">
                            <button type="button" class="btn btn-outline-danger btn-sm remove-btn" title="Remove this button"><i class="bi bi-x"></i></button>
                        </div>
                        <div class="btn-url-row ${isUrl ? '' : 'd-none'}">
                            <input type="url" class="form-control form-control-sm btn-url" value="${escapeHtml(btn.url || '')}" placeholder="https://your-link.com">
                        </div>
                        <div class="btn-target-row ${isUrl ? 'd-none' : ''}">
                            <div class="d-flex align-items-center gap-2">
                                <small class="text-muted">When tapped:</small>
                                <select class="form-select form-select-sm btn-target">
                                    ${buildTargetOptions(btn.target_node_id, index)}
                                </select>
                            </div>
                        </div>
                    </div>
                `;
            });
            html = `
                <div class="mb-3">
                    <label class="form-label">Your message</label>
                    <textarea class="form-control node-field" data-field="text" rows="2" placeholder="e.g., Choose an option below 👇">${escapeHtml(node.config.text || '')}</textarea>
                </div>
                ${buildVariationsSection(node, index)}
                <label class="form-label">Buttons</label>
                <small class="text-muted d-block mb-2">Action = next step, Link = opens URL</small>
                <div class="btn-container">${btnHtml}</div>
                <button type="button" class="btn btn-outline-primary btn-sm add-btn mt-2"><i class="bi bi-plus me-1"></i>Add Button</button>
            `;
            break;

        case 'condition_follower':
            html = `
                <div class="alert alert-light small mb-2 border py-1 px-2">
                    <i class="bi bi-lightbulb me-1 text-warning"></i>
                    Routes based on follow status
                </div>
                <div class="form-node-connection follower mb-2">
                    <div class="connection-label"><i class="bi bi-check-circle text-success me-1"></i>If they <strong>follow</strong> you:</div>
                    <select class="form-select form-select-sm follower-target" data-branch="true">
                        ${buildTargetOptions(node.config.true_node_id, index)}
                    </select>
                </div>
                <div class="form-node-connection not-follower">
                    <div class="connection-label"><i class="bi bi-x-circle text-danger me-1"></i>If they <strong>don't follow</strong> you:</div>
                    <select class="form-select form-select-sm follower-target" data-branch="false">
                        ${buildTargetOptions(node.config.false_node_id, index)}
                    </select>
                </div>
            `;
            break;

        case 'condition_user_interacted':
            const timePeriodLabels = { 'ever': 'Ever', '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days' };
            const currentTimePeriod = node.config.time_period || 'ever';
            html = `
                <div class="alert alert-light small mb-2 border py-1 px-2">
                    <i class="bi bi-lightbulb me-1 text-warning"></i>
                    Routes new vs returning users
                </div>
                <div class="mb-3">
                    <label class="form-label">Check within</label>
                    <select class="form-select form-select-sm node-field" data-field="time_period">
                        <option value="ever" ${currentTimePeriod === 'ever' ? 'selected' : ''}>All time</option>
                        <option value="24h" ${currentTimePeriod === '24h' ? 'selected' : ''}>Last 24 hours</option>
                        <option value="7d" ${currentTimePeriod === '7d' ? 'selected' : ''}>Last 7 days</option>
                        <option value="30d" ${currentTimePeriod === '30d' ? 'selected' : ''}>Last 30 days</option>
                    </select>
                </div>
                <div class="form-node-connection returning mb-2">
                    <div class="connection-label"><i class="bi bi-arrow-repeat text-success me-1"></i>If <strong>returning</strong> user:</div>
                    <select class="form-select form-select-sm user-interacted-target" data-branch="true">
                        ${buildTargetOptions(node.config.true_node_id, index)}
                    </select>
                </div>
                <div class="form-node-connection new-user">
                    <div class="connection-label"><i class="bi bi-person-plus text-info me-1"></i>If <strong>first time</strong> user:</div>
                    <select class="form-select form-select-sm user-interacted-target" data-branch="false">
                        ${buildTargetOptions(node.config.false_node_id, index)}
                    </select>
                </div>
            `;
            break;

        case 'collect_data':
            const sidebarFieldType = node.config.field_type || 'email';
            const sidebarIsCustom = sidebarFieldType === 'custom';
            const sidebarVarName = sidebarIsCustom
                ? (node.config.variable_name || `custom_${Math.random().toString(36).substring(2, 8)}`)
                : `collected_${sidebarFieldType}`;
            const sidebarFieldLabel = node.config.field_label || '';
            html = `
                <div class="alert alert-light small mb-2 border py-1 px-2">
                    <i class="bi bi-lightbulb me-1 text-warning"></i>
                    Asks a question, saves response to Leads
                </div>
                <div class="mb-3">
                    <label class="form-label">What info do you want to collect?</label>
                    <select class="form-select node-field collect-field-type" data-field="field_type" data-node-index="${index}">
                        <option value="name" ${sidebarFieldType === 'name' ? 'selected' : ''}>Their Name</option>
                        <option value="email" ${sidebarFieldType === 'email' ? 'selected' : ''}>Their Email</option>
                        <option value="phone" ${sidebarFieldType === 'phone' ? 'selected' : ''}>Their Phone Number</option>
                        <option value="custom" ${sidebarFieldType === 'custom' ? 'selected' : ''}>Something Else (Custom)</option>
                    </select>
                </div>
                <div class="mb-3 collect-label-group ${sidebarIsCustom ? '' : 'd-none'}" data-node-index="${index}">
                    <label class="form-label">Label for this field</label>
                    <input type="text" class="form-control node-field" data-field="field_label" value="${escapeHtml(sidebarFieldLabel)}" placeholder="e.g., Company Name, Budget, etc.">
                    <small class="text-muted">Shown in Leads</small>
                </div>
                <div class="mb-3">
                    <label class="form-label">Your question to the user</label>
                    <textarea class="form-control node-field" data-field="prompt_text" rows="2" placeholder="e.g., What's your email address?">${escapeHtml(node.config.prompt_text || '')}</textarea>
                </div>
                <input type="hidden" class="node-field collect-var-input" data-field="variable_name" data-node-index="${index}" value="${escapeHtml(sidebarVarName)}">
                <div class="form-node-connection next-node">
                    <div class="connection-label"><i class="bi bi-arrow-right-circle text-primary me-1"></i>After they respond:</div>
                    <select class="form-select form-select-sm next-node-select">
                        ${buildTargetOptions(node.nextNodeId, index)}
                    </select>
                </div>
            `;
            break;

        case 'ai_conversation':
            if (node.dbId) {
                // Node is saved - show configure button
                const configUrl = `/instagram/ai/node/${node.dbId}/config/`;
                const agentName = node.config.agent_name || 'Not set up yet';
                const goal = node.config.goal || 'Not configured';
                html = `
                    <div class="alert alert-light small mb-2 border py-1 px-2">
                        <i class="bi bi-lightbulb me-1 text-warning"></i>
                        AI chats with user until goal is reached
                    </div>
                    <div class="mb-2">
                        <label class="form-label small text-muted mb-1">AI Agent</label>
                        <div class="form-control form-control-sm bg-light">${escapeHtml(agentName)}</div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label small text-muted mb-1">Goal</label>
                        <div class="form-control form-control-sm bg-light" style="min-height:40px;white-space:pre-wrap;font-size:12px;">${escapeHtml(goal)}</div>
                    </div>
                    <a href="${configUrl}" class="btn btn-primary btn-sm w-100 mb-3">
                        <i class="bi bi-gear me-1"></i>Set Up AI Agent
                    </a>
                    <div class="form-node-connection next-node">
                        <div class="connection-label"><i class="bi bi-arrow-right-circle text-primary me-1"></i>When goal is completed:</div>
                        <select class="form-select form-select-sm next-node-select">
                            ${buildTargetOptions(node.nextNodeId, index)}
                        </select>
                    </div>
                `;
            } else {
                // Node not saved yet
                html = `
                    <div class="alert alert-warning small mb-2 py-1 px-2">
                        <i class="bi bi-exclamation-triangle me-1"></i>
                        Save flow first, then set up AI agent
                    </div>
                    <button type="button" class="btn btn-secondary btn-sm w-100 mb-3" disabled>
                        <i class="bi bi-gear me-1"></i>Set Up AI Agent
                    </button>
                    <div class="form-node-connection next-node">
                        <div class="connection-label"><i class="bi bi-arrow-right-circle text-primary me-1"></i>When goal is completed:</div>
                        <select class="form-select form-select-sm next-node-select">
                            ${buildTargetOptions(node.nextNodeId, index)}
                        </select>
                    </div>
                `;
            }
            break;
    }

    return html;
}

// Build variations section for message nodes
function buildVariationsSection(node, index) {
    const variations = node.config.variations || [];
    const hasVariations = variations.length > 0;
    const variationsHtml = variations.map((v, i) => `
        <div class="variation-item d-flex gap-2 mb-2" data-variation-index="${i}">
            <textarea class="form-control form-control-sm variation-text" rows="2" placeholder="Alternative message ${i + 1}">${escapeHtml(v || '')}</textarea>
            <button type="button" class="btn btn-outline-danger btn-sm remove-variation align-self-start"><i class="bi bi-x"></i></button>
        </div>
    `).join('');

    return `
        <div class="mb-3 variations-section">
            <div class="d-flex align-items-center gap-2 mb-2">
                <button type="button" class="btn btn-sm ${hasVariations ? 'btn-outline-secondary' : 'btn-outline-primary'} toggle-variations" data-node-index="${index}">
                    <i class="bi bi-shuffle me-1"></i>Variations ${hasVariations ? `(${variations.length})` : ''}
                </button>
                <small class="text-muted">Sends one at random</small>
            </div>
            <div class="variations-container ${hasVariations ? '' : 'd-none'}">
                <div class="variations-list">${variationsHtml}</div>
                <button type="button" class="btn btn-outline-primary btn-sm add-variation mt-1">
                    <i class="bi bi-plus me-1"></i>Add Variation
                </button>
                <div class="small text-muted mt-2">
                    <i class="bi bi-info-circle me-1"></i>If variations exist, the main message above is ignored. One variation is randomly selected each time.
                </div>
            </div>
        </div>
    `;
}

// Build target node dropdown options
function buildTargetOptions(selectedId, excludeIndex = -1) {
    let options = '<option value="">🛑 End conversation</option>';

    formNodes.forEach((n, i) => {
        // Skip current node to prevent self-reference
        if (i === excludeIndex) return;

        const info = NODE_TYPES[n.type];
        const label = `Step ${i + 1}: ${info?.title || n.type}`;
        // Match by dbId (for existing nodes) or tempId (for new nodes)
        const isSelected = (selectedId && (selectedId == n.dbId || selectedId == n.tempId)) ? 'selected' : '';
        options += `<option value="${n.dbId || n.tempId}" ${isSelected}>➡️ ${label}</option>`;
    });

    return options;
}

// Attach all event handlers for form editor (only once)
function attachFormEventHandlers() {
    if (formEventHandlersAttached) return;
    formEventHandlersAttached = true;

    const container = document.getElementById('formNodesContainer');

    // Use event delegation for better performance
    container.addEventListener('click', function(e) {
        const target = e.target.closest('button');
        if (!target) return;

        const card = target.closest('.form-node-card');
        if (!card) return;
        const nodeIndex = parseInt(card.dataset.nodeIndex);

        if (target.closest('.delete-node-btn')) {
            e.stopPropagation();
            if (confirm('Delete this node?')) {
                formNodes.splice(nodeIndex, 1);
                renderFormEditor();
                showToast('Node deleted');
            }
            return;
        } else if (target.closest('.add-qr')) {
            if (formNodes[nodeIndex].quickReplies.length >= 13) {
                showToast('Maximum 13 buttons', 'error');
                return;
            }
            formNodes[nodeIndex].quickReplies.push({ title: '', payload: `qr_${Date.now()}`, targetNodeId: null });
            renderFormEditor();
        } else if (target.closest('.remove-qr')) {
            const qrDiv = target.closest('[data-qr-index]');
            const qrIndex = parseInt(qrDiv.dataset.qrIndex);
            formNodes[nodeIndex].quickReplies.splice(qrIndex, 1);
            renderFormEditor();
        } else if (target.closest('.add-btn')) {
            if (!formNodes[nodeIndex].config.buttons) formNodes[nodeIndex].config.buttons = [];
            if (formNodes[nodeIndex].config.buttons.length >= 3) {
                showToast('Maximum 3 buttons', 'error');
                return;
            }
            formNodes[nodeIndex].config.buttons.push({ type: 'postback', title: '', payload: `btn_${Date.now()}` });
            renderFormEditor();
        } else if (target.closest('.remove-btn')) {
            const btnDiv = target.closest('[data-btn-index]');
            const btnIndex = parseInt(btnDiv.dataset.btnIndex);
            formNodes[nodeIndex].config.buttons.splice(btnIndex, 1);
            renderFormEditor();
        } else if (target.closest('.toggle-variations')) {
            const variationsContainer = card.querySelector('.variations-container');
            variationsContainer.classList.toggle('d-none');
            const btn = target.closest('.toggle-variations');
            btn.classList.toggle('btn-outline-primary');
            btn.classList.toggle('btn-outline-secondary');
        } else if (target.closest('.add-variation')) {
            if (!formNodes[nodeIndex].config.variations) formNodes[nodeIndex].config.variations = [];
            if (formNodes[nodeIndex].config.variations.length >= 10) {
                showToast('Maximum 10 variations', 'error');
                return;
            }
            formNodes[nodeIndex].config.variations.push('');
            renderFormEditor();
            // Re-open the variations section
            setTimeout(() => {
                const newCard = document.querySelector(`.form-node-card[data-node-index="${nodeIndex}"]`);
                if (newCard) {
                    const container = newCard.querySelector('.variations-container');
                    if (container) container.classList.remove('d-none');
                }
            }, 0);
        } else if (target.closest('.remove-variation')) {
            const varDiv = target.closest('[data-variation-index]');
            const varIndex = parseInt(varDiv.dataset.variationIndex);
            formNodes[nodeIndex].config.variations.splice(varIndex, 1);
            renderFormEditor();
            // Re-open the variations section if there are still variations
            setTimeout(() => {
                const newCard = document.querySelector(`.form-node-card[data-node-index="${nodeIndex}"]`);
                if (newCard && formNodes[nodeIndex].config.variations?.length > 0) {
                    const container = newCard.querySelector('.variations-container');
                    if (container) container.classList.remove('d-none');
                }
            }, 0);
        }
    });

    // Input/select change handlers
    container.addEventListener('change', function(e) {
        const card = e.target.closest('.form-node-card');
        if (!card) return;
        const nodeIndex = parseInt(card.dataset.nodeIndex);
        const node = formNodes[nodeIndex];

        // Simple config fields
        if (e.target.classList.contains('node-field')) {
            const field = e.target.dataset.field;
            node.config[field] = e.target.value;

            // Auto-update variable_name and toggle field_label visibility for collect_data nodes
            if (field === 'field_type' && node.type === 'collect_data') {
                const varNameInput = card.querySelector('.collect-var-input');
                const labelGroup = card.querySelector('.collect-label-group');
                const isCustom = e.target.value === 'custom';

                if (isCustom) {
                    // Custom: show label field, generate random var name
                    if (labelGroup) labelGroup.classList.remove('d-none');
                    if (varNameInput && (!varNameInput.value || !varNameInput.value.startsWith('custom_'))) {
                        varNameInput.value = `custom_${Math.random().toString(36).substring(2, 8)}`;
                        node.config.variable_name = varNameInput.value;
                    }
                } else {
                    // Preset types: hide label field, auto-generate var name
                    if (labelGroup) labelGroup.classList.add('d-none');
                    if (varNameInput) {
                        varNameInput.value = `collected_${e.target.value}`;
                        node.config.variable_name = varNameInput.value;
                    }
                    node.config.field_label = '';
                }
            }
        }
        // Quick reply title
        else if (e.target.classList.contains('qr-title')) {
            const qrIndex = parseInt(e.target.closest('[data-qr-index]').dataset.qrIndex);
            node.quickReplies[qrIndex].title = e.target.value;
        }
        // Quick reply target
        else if (e.target.classList.contains('qr-target')) {
            const qrIndex = parseInt(e.target.closest('[data-qr-index]').dataset.qrIndex);
            node.quickReplies[qrIndex].targetNodeId = e.target.value || null;
        }
        // Button type
        else if (e.target.classList.contains('btn-type')) {
            const btnIndex = parseInt(e.target.closest('[data-btn-index]').dataset.btnIndex);
            node.config.buttons[btnIndex].type = e.target.value;
            const btnDiv = e.target.closest('[data-btn-index]');
            btnDiv.querySelector('.btn-url-row').classList.toggle('d-none', e.target.value !== 'web_url');
            btnDiv.querySelector('.btn-target-row').classList.toggle('d-none', e.target.value === 'web_url');
        }
        // Button title
        else if (e.target.classList.contains('btn-title')) {
            const btnIndex = parseInt(e.target.closest('[data-btn-index]').dataset.btnIndex);
            node.config.buttons[btnIndex].title = e.target.value;
        }
        // Button URL
        else if (e.target.classList.contains('btn-url')) {
            const btnIndex = parseInt(e.target.closest('[data-btn-index]').dataset.btnIndex);
            node.config.buttons[btnIndex].url = e.target.value;
        }
        // Button target
        else if (e.target.classList.contains('btn-target')) {
            const btnIndex = parseInt(e.target.closest('[data-btn-index]').dataset.btnIndex);
            node.config.buttons[btnIndex].target_node_id = e.target.value || null;
        }
        // Follower check targets
        else if (e.target.classList.contains('follower-target')) {
            const branch = e.target.dataset.branch;
            if (branch === 'true') {
                node.config.true_node_id = e.target.value || null;
            } else {
                node.config.false_node_id = e.target.value || null;
            }
        }
        // User interacted check targets
        else if (e.target.classList.contains('user-interacted-target')) {
            const branch = e.target.dataset.branch;
            if (branch === 'true') {
                node.config.true_node_id = e.target.value || null;
            } else {
                node.config.false_node_id = e.target.value || null;
            }
        }
        // Next node selector
        else if (e.target.classList.contains('next-node-select')) {
            node.nextNodeId = e.target.value || null;
        }
        // Variation text
        else if (e.target.classList.contains('variation-text')) {
            const varIndex = parseInt(e.target.closest('[data-variation-index]').dataset.variationIndex);
            if (!node.config.variations) node.config.variations = [];
            node.config.variations[varIndex] = e.target.value;
        }
    });

    // Also listen for input events (real-time updates for textareas)
    container.addEventListener('input', function(e) {
        const card = e.target.closest('.form-node-card');
        if (!card) return;
        const nodeIndex = parseInt(card.dataset.nodeIndex);
        const node = formNodes[nodeIndex];

        // Variation text (input event for real-time updates)
        if (e.target.classList.contains('variation-text')) {
            const varIndex = parseInt(e.target.closest('[data-variation-index]').dataset.variationIndex);
            if (!node.config.variations) node.config.variations = [];
            node.config.variations[varIndex] = e.target.value;
        }
        // Also handle main text field
        else if (e.target.classList.contains('node-field') && e.target.tagName === 'TEXTAREA') {
            const field = e.target.dataset.field;
            node.config[field] = e.target.value;
        }
    });
}

// Add node from dropdown (form editor)
document.querySelectorAll('[data-add-node]').forEach(item => {
    item.addEventListener('click', function(e) {
        e.preventDefault();
        if (currentEditorMode !== 'form') return;

        const nodeType = this.dataset.addNode;

        // Validate follower check
        if (nodeType === 'condition_follower') {
            const hasInteraction = formNodes.some(n =>
                n.type === 'message_quick_reply' || n.type === 'message_button_template'
            );
            if (!hasInteraction) {
                showToast('Add a Quick Reply or Button Template first', 'error');
                return;
            }
        }

        const newNode = {
            tempId: `node_${formNodeIdCounter++}`,
            dbId: null,
            type: nodeType,
            config: {},
            quickReplies: nodeType === 'message_quick_reply' ? [{ title: '', payload: 'qr_0', targetNodeId: null }] : [],
            nextNodeId: null
        };

        if (nodeType === 'message_button_template') {
            newNode.config.buttons = [{ type: 'postback', title: '', payload: 'btn_0' }];
        }

        if (nodeType === 'condition_user_interacted') {
            newNode.config.time_period = 'ever';
        }

        formNodes.push(newNode);
        renderFormEditor();
        showToast('Node added');
    });
});

// Form editor save function - Clean rewrite
function saveFormFlow() {
    if (formNodes.length === 0) {
        showToast('Add at least one node to save', 'error');
        return;
    }

    // Build nodes array for saving - Use explicit nextNodeId, no auto-connect
    const nodes = formNodes.map((node, index) => {
        // Filter out empty variations before saving
        let config = { ...node.config };
        if (config.variations) {
            config.variations = config.variations.filter(v => v && v.trim());
            if (config.variations.length === 0) {
                delete config.variations;
            }
        }

        const nodeData = {
            id: node.dbId || null,
            temp_id: node.tempId,
            order: index,
            node_type: node.type,
            config: config,
            quick_replies: [],
            // Use explicit next node (null if not set)
            next_node_id: node.nextNodeId || null,
            // Send positions same way Visual Editor does (separate fields)
            pos_x: node._pos_x,
            pos_y: node._pos_y
        };

        // Handle quick replies (message_quick_reply nodes)
        if (node.type === 'message_quick_reply' && node.quickReplies) {
            nodeData.quick_replies = node.quickReplies.map(qr => ({
                title: qr.title || '',
                payload: qr.payload || '',
                target_node_id: qr.targetNodeId || null
            }));
        }

        return nodeData;
    });

    // Validate message text lengths before saving
    const validation = validateNodeTextLengths(nodes);
    if (!validation.valid) {
        showToast(validation.error, 'error');
        return;
    }

    // Validate required fields for each node type
    const requiredValidation = validateRequiredFields(nodes);
    if (!requiredValidation.valid) {
        showToast(requiredValidation.error, 'error');
        return;
    }

    // Validate no consecutive message nodes without interaction
    const msgValidation = validateConsecutiveMessages(nodes);
    if (!msgValidation.valid) {
        showToast(msgValidation.error, 'error');
        return;
    }

    // Validate follower check placement (requires prior interaction)
    const followerValidation = validateFollowerCheckPlacement(nodes);
    if (!followerValidation.valid) {
        showToast(followerValidation.error, 'error');
        return;
    }

    const saveBtn = document.getElementById('saveFlowBtn');
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
        // Check if redirected (e.g., to login page)
        if (response.redirected) {
            throw new Error('Session expired. Please refresh the page and try again.');
        }
        // Check content type to ensure it's JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Server returned non-JSON response. You may need to log in again.');
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
            // Check if there are new AI nodes that need configuration
            if (data.ai_config_urls && Object.keys(data.ai_config_urls).length > 0) {
                const aiNodeIds = Object.keys(data.ai_config_urls);
                const firstAiUrl = data.ai_config_urls[aiNodeIds[0]];
                if (confirm('AI Conversation node added! Would you like to configure it now?')) {
                    window.location.href = firstAiUrl;
                    return;
                }
            }
            showToast('Flow saved successfully!', 'success');
            // Reload to show saved data
            location.reload();
        } else {
            showToast(data.error || 'Failed to save flow', 'error');
            saveBtn.disabled = false;
            saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save';
        }
    })
    .catch(error => {
        console.error('[FORM SAVE] Error:', error);
        showToast('Failed to save: ' + error.message, 'error');
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save';
    });
}

// ============================================================================
// Flow Settings
// ============================================================================

// Toggle keywords section based on trigger type (Visual Editor sidebar)
const settingsTriggerType = document.getElementById('settingsTriggerType');
const settingsKeywordsSection = document.getElementById('settingsKeywordsSection');

if (settingsTriggerType && settingsKeywordsSection) {
    function toggleSettingsKeywords() {
        settingsKeywordsSection.style.display = settingsTriggerType.value === 'comment_keyword' ? 'block' : 'none';
    }
    settingsTriggerType.addEventListener('change', toggleSettingsKeywords);
    toggleSettingsKeywords();
}

// Toggle keywords section (Form Editor)
const formTriggerType = document.getElementById('formTriggerType');
const formKeywordsCol = document.getElementById('formKeywordsCol');

if (formTriggerType && formKeywordsCol) {
    function toggleFormKeywords() {
        formKeywordsCol.style.display = formTriggerType.value === 'comment_keyword' ? 'block' : 'none';
    }
    formTriggerType.addEventListener('change', toggleFormKeywords);
    toggleFormKeywords();
}

// Browse posts button
const settingsBrowsePostsBtn = document.getElementById('settingsBrowsePostsBtn');
const settingsPostId = document.getElementById('settingsPostId');

if (settingsBrowsePostsBtn) {
    settingsBrowsePostsBtn.addEventListener('click', function() {
        const modal = new bootstrap.Modal(document.getElementById('postSelectModal'));
        modal.show();
        loadPostsForSettings();
    });
}

// Clear post button (Visual Editor)
const settingsClearPostBtn = document.getElementById('settingsClearPostBtn');
if (settingsClearPostBtn) {
    settingsClearPostBtn.addEventListener('click', function() {
        settingsPostId.value = '';
        this.style.display = 'none';
    });
}

// Form Editor - Browse posts button
const formBrowsePostsBtn = document.getElementById('formBrowsePostsBtn');
const formPostId = document.getElementById('formPostId');

if (formBrowsePostsBtn) {
    formBrowsePostsBtn.addEventListener('click', function() {
        const modal = new bootstrap.Modal(document.getElementById('postSelectModal'));
        modal.show();
        loadPostsForForm();
    });
}

// Form Editor - Clear post button
const formClearPostBtn = document.getElementById('formClearPostBtn');
if (formClearPostBtn) {
    formClearPostBtn.addEventListener('click', function() {
        formPostId.value = '';
        this.style.display = 'none';
    });
}

// Load posts for form editor modal
function loadPostsForForm() {
    const loading = document.getElementById('postsLoading');
    const grid = document.getElementById('postsGrid');
    const error = document.getElementById('postsError');

    loading.style.display = 'block';
    grid.style.display = 'none';
    error.style.display = 'none';

    fetch(postsApiUrl)
        .then(response => response.json())
        .then(data => {
            loading.style.display = 'none';
            if (data.success) {
                grid.innerHTML = '';
                data.posts.forEach(post => {
                    const col = document.createElement('div');
                    col.className = 'col-4 col-md-3';
                    const imgUrl = post.media_type === 'VIDEO'
                        ? (post.thumbnail_url || '/static/img/placeholder.png')
                        : (post.media_url || post.thumbnail_url || '/static/img/placeholder.png');
                    const isVideo = post.media_type === 'VIDEO';
                    col.innerHTML = `
                        <div class="post-item border rounded p-1 position-relative" style="cursor: pointer;">
                            <img src="${imgUrl}" class="img-fluid rounded" style="aspect-ratio: 1; object-fit: cover; width: 100%;">
                            ${isVideo ? '<span class="position-absolute top-50 start-50 translate-middle text-white"><i class="bi bi-play-circle-fill fs-3"></i></span>' : ''}
                        </div>
                    `;
                    col.querySelector('.post-item').addEventListener('click', function() {
                        formPostId.value = post.id;
                        // Also update the sidebar input if exists
                        if (settingsPostId) settingsPostId.value = post.id;
                        bootstrap.Modal.getInstance(document.getElementById('postSelectModal')).hide();
                        // Show clear buttons
                        if (formClearPostBtn) formClearPostBtn.style.display = 'block';
                        if (settingsClearPostBtn) settingsClearPostBtn.style.display = 'block';
                    });
                    grid.appendChild(col);
                });
                grid.style.display = 'flex';
            } else {
                error.textContent = data.error || 'Failed to load posts';
                error.style.display = 'block';
            }
        })
        .catch(err => {
            loading.style.display = 'none';
            error.textContent = 'Error loading posts';
            error.style.display = 'block';
        });
}

// Load posts for settings modal
function loadPostsForSettings() {
    const loading = document.getElementById('postsLoading');
    const grid = document.getElementById('postsGrid');
    const error = document.getElementById('postsError');

    loading.style.display = 'block';
    grid.style.display = 'none';
    error.style.display = 'none';

    fetch(postsApiUrl)
        .then(response => response.json())
        .then(data => {
            loading.style.display = 'none';
            if (data.success) {
                grid.innerHTML = '';
                data.posts.forEach(post => {
                    const col = document.createElement('div');
                    col.className = 'col-4 col-md-3';
                    const imgUrl = post.media_type === 'VIDEO'
                        ? (post.thumbnail_url || '/static/img/placeholder.png')
                        : (post.media_url || post.thumbnail_url || '/static/img/placeholder.png');
                    const isVideo = post.media_type === 'VIDEO';
                    col.innerHTML = `
                        <div class="post-item border rounded p-1 position-relative" style="cursor: pointer;">
                            <img src="${imgUrl}" class="img-fluid rounded" style="aspect-ratio: 1; object-fit: cover; width: 100%;">
                            ${isVideo ? '<span class="position-absolute top-50 start-50 translate-middle text-white"><i class="bi bi-play-circle-fill fs-3"></i></span>' : ''}
                        </div>
                    `;
                    col.querySelector('.post-item').addEventListener('click', function() {
                        settingsPostId.value = post.id;
                        bootstrap.Modal.getInstance(document.getElementById('postSelectModal')).hide();
                        // Show clear button
                        const clearBtn = document.getElementById('settingsClearPostBtn');
                        if (clearBtn) clearBtn.style.display = 'block';
                    });
                    grid.appendChild(col);
                });
                grid.style.display = 'flex';
            } else {
                error.textContent = data.error || 'Failed to load posts';
                error.style.display = 'block';
            }
        })
        .catch(err => {
            loading.style.display = 'none';
            error.textContent = 'Error loading posts';
            error.style.display = 'block';
        });
}

// ============================================================================
// Initialize
// ============================================================================

loadExistingFlow();
updateFollowerCheckPaletteState();


// ============================================================================
// Collapsible Left Panel Controls
// ============================================================================

const leftPanelCol = document.getElementById('leftPanelCol');
const centerPanelCol = document.getElementById('centerPanelCol');
const toggleLeftPanel = document.getElementById('toggleLeftPanel');
const floatingToggleLeft = document.getElementById('floatingToggleLeft');

// Load saved panel state
const leftPanelCollapsed = localStorage.getItem('flowEditorLeftPanelCollapsed') === 'true';

function updateColumnWidths() {
    const leftCollapsed = leftPanelCol.classList.contains('collapsed');

    // Remove all width classes first
    centerPanelCol.classList.remove('col-md-8', 'col-md-10');

    if (leftCollapsed) {
        centerPanelCol.classList.add('col-md-10');
    } else {
        centerPanelCol.classList.add('col-md-8');
    }

    // Refresh drawflow after layout change
    setTimeout(() => {
        if (editor) {
            editor.zoom_refresh();
        }
    }, 350);
}

function toggleLeftPanelFn() {
    leftPanelCol.classList.toggle('collapsed');
    const isCollapsed = leftPanelCol.classList.contains('collapsed');

    // Update toggle button icon
    const icon = toggleLeftPanel.querySelector('i');
    icon.className = isCollapsed ? 'bi bi-chevron-right' : 'bi bi-chevron-left';

    // Show/hide floating button
    floatingToggleLeft.classList.toggle('visible', isCollapsed);

    // Save state
    localStorage.setItem('flowEditorLeftPanelCollapsed', isCollapsed);

    updateColumnWidths();
}

// Initialize panel state
if (leftPanelCollapsed) {
    leftPanelCol.classList.add('collapsed');
    toggleLeftPanel.querySelector('i').className = 'bi bi-chevron-right';
    floatingToggleLeft.classList.add('visible');
    updateColumnWidths();
}

// Event listeners
toggleLeftPanel?.addEventListener('click', toggleLeftPanelFn);
floatingToggleLeft?.addEventListener('click', toggleLeftPanelFn);

// ============================================================================
// Mobile: Setup bottom action bar
// ============================================================================

function setupMobileBottomBar() {
    const isMobile = window.innerWidth <= 768;
    const addNodeSection = document.querySelector('.add-node-section');
    const addNodeDropdown = document.querySelector('.add-node-dropdown');
    const originalSaveBtn = document.getElementById('saveFlowBtn');

    if (!addNodeDropdown) return;

    // Add dropup class on mobile
    if (isMobile) {
        addNodeDropdown.classList.add('dropup');
    } else {
        addNodeDropdown.classList.remove('dropup');
    }

    // Add save button to bottom bar on mobile
    let mobileSaveBtn = document.getElementById('mobileSaveBtn');

    if (isMobile && addNodeSection) {
        if (!mobileSaveBtn) {
            mobileSaveBtn = document.createElement('button');
            mobileSaveBtn.id = 'mobileSaveBtn';
            mobileSaveBtn.className = 'btn btn-success mobile-bottom-save mt-2';
            mobileSaveBtn.style.cssText = 'width: 100%; padding: 14px 20px; font-size: 15px; font-weight: 600; border-radius: 12px; background: #198754; color: white; border: none; display: flex; align-items: center; justify-content: center; gap: 8px;';
            mobileSaveBtn.innerHTML = '<i class="bi bi-check-lg"></i> Save Changes';
            mobileSaveBtn.onclick = function(e) {
                e.preventDefault();
                if (originalSaveBtn) originalSaveBtn.click();
            };
            addNodeSection.appendChild(mobileSaveBtn);
        }
    } else if (mobileSaveBtn) {
        mobileSaveBtn.remove();
    }
}

// Run on load and resize
setupMobileBottomBar();
window.addEventListener('resize', setupMobileBottomBar);

// Run when switching to form mode
document.querySelectorAll('#editorModeToggle button').forEach(btn => {
    btn.addEventListener('click', () => setTimeout(setupMobileBottomBar, 150));
});
