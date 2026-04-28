import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { FaPaperPlane, FaTimes } from 'react-icons/fa';
import { HiOutlineSparkles, HiOutlineChatBubbleLeftRight, HiOutlineMicrophone, HiOutlineArrowPath } from 'react-icons/hi2';
import Lottie from 'lottie-react';
import api from '../api';
import Swal from 'sweetalert2';
import './FloatingChatbot.css';

const ROLE_COPY = {
  Admin: {
    title: 'Admin Assistant',
    prompts: [
      "Show today attendance list",
      "Show today's punchin details",
      'Show pending approvals',
      'Download employee report',
    ],
  },
  Manager: {
    title: 'Manager Assistant',
    prompts: [
      'Show my reportees on leave today',
      'Show my reportee punchin details',
      'Show my pending approvals',
      'Download employee report',
    ],
  },
  Default: {
    title: 'Employee Assistant',
    prompts: [
      "Show my leave balance",
      "Show my attendance today",
      "Show my profile details",
    ],
  },
};

const getRoleLabel = (role) => {
  if (role === 'Admin') return 'an admin';
  if (role === 'Manager') return 'a manager';
  return 'an employee';
};



const normalizeEmployeeId = (value) => {
  const cleaned = value.trim().toUpperCase().replace(/\s+/g, '');
  if (!cleaned) return '';
  return cleaned;
};

const extractEmployeeIdFromText = (value) => {
  const match = value.toUpperCase().match(/\b[A-Z]{2,}\s*\d+\b/);
  if (!match) return '';
  return normalizeEmployeeId(match[0]);
};

const parseReportPeriod = (value) => {
  const input = value.trim().toLowerCase();
  const currentDate = new Date();
  const currentYear = currentDate.getFullYear();
  const isoDate = (date) => date.toISOString().split('T')[0];

  if (!input) return null;

  if (input.includes('current week') || input === 'weekly' || input === 'week') {
    const currentDay = currentDate.getDay();
    const mondayOffset = currentDay === 0 ? -6 : 1 - currentDay;
    const startDate = new Date(currentDate);
    startDate.setDate(currentDate.getDate() + mondayOffset);
    const endDate = new Date(startDate);
    endDate.setDate(startDate.getDate() + 6);
    return {
      type: 'weekly',
      query: { from: isoDate(startDate), to: isoDate(endDate) },
      label: 'current week',
    };
  }

  if (input.includes('last week')) {
    const currentDay = currentDate.getDay();
    const mondayOffset = currentDay === 0 ? -6 : 1 - currentDay;
    const startDate = new Date(currentDate);
    startDate.setDate(currentDate.getDate() + mondayOffset - 7);
    const endDate = new Date(startDate);
    endDate.setDate(startDate.getDate() + 6);
    return {
      type: 'weekly',
      query: { from: isoDate(startDate), to: isoDate(endDate) },
      label: 'last week',
    };
  }

  if (input.includes('current month') || input === 'monthly' || input === 'month') {
    const monthValue = `${currentYear}-${String(currentDate.getMonth() + 1).padStart(2, '0')}`;
    return {
      type: 'monthly',
      query: { months: monthValue },
      label: 'current month',
    };
  }

  if (input.includes('current year') || input === 'yearly' || input === 'year') {
    return {
      type: 'yearly',
      query: { year: String(currentYear) },
      label: String(currentYear),
    };
  }

  const monthMatch = input.match(
    /\b(january|february|march|april|may|june|july|august|september|october|november|december)\b(?:\s+(\d{4}))?/i
  );
  if (monthMatch) {
    const monthName = monthMatch[1];
    const year = monthMatch[2] || String(currentYear);
    const monthDate = new Date(`${monthName} 1, ${year}`);
    if (!Number.isNaN(monthDate.getTime())) {
      const monthValue = `${year}-${String(monthDate.getMonth() + 1).padStart(2, '0')}`;
      return {
        type: 'monthly',
        query: { months: monthValue },
        label: `${monthName} ${year}`,
      };
    }
  }

  const yearMatch = input.match(/\b(20\d{2})\b/);
  if (yearMatch && (input.includes('year') || input === yearMatch[1])) {
    return {
      type: 'yearly',
      query: { year: yearMatch[1] },
      label: yearMatch[1],
    };
  }

  return null;
};

const extractDownloadReportDetails = (value) => ({
  employeeId: extractEmployeeIdFromText(value),
  period: parseReportPeriod(value),
});

const looksLikeGeneralQuestion = (value) => {
  const input = value.trim().toLowerCase();
  if (!input) return false;

  const generalQuestionPatterns = [
    'tell me about',
    'what is',
    'who is',
    'where is',
    'when is',
    'why is',
    'how is',
    'can you',
    'could you',
    'please show',
    'show me',
    'give me',
    'explain',
  ];

  if (generalQuestionPatterns.some((pattern) => input.includes(pattern))) {
    return true;
  }

  return !input.includes('report') && !extractEmployeeIdFromText(value) && !parseReportPeriod(value);
};

const isOutofScope = (value) => {
  const input = value.trim().toLowerCase();
  // Allow greetings and common question words
  const conversationKeywords = ['hi', 'hello', 'hey', 'good', 'morning', 'afternoon', 'evening', 'how', 'who', 'what', 'where', 'when', 'why', 'can', 'could', 'please', 'thanks', 'thank'];
  const hrKeywords = ['leave', 'attendance', 'profile', 'report', 'access', 'help', 'employee', 'emp'];
  
  const allKeywords = [...conversationKeywords, ...hrKeywords];
  return !allKeywords.some(keyword => input.includes(keyword));
};

const buildAssistantReply = (role, input) => {
  const message = input.trim().toLowerCase();
  if (!message) {
    return 'Type a question and I will help.';
  }

  if (/^(hi|hello|hey)\b/.test(message)) {
    return `Hello. I can help you as ${getRoleLabel(role)} with access guidance and common HR workflow questions.`;
  }

  if (message.includes('who can access') || message.includes('my access') || message.includes('what can i access') || message.includes('role access')) {
    if (role === 'Admin') {
      return 'As Admin, you can access organization-wide employee data and your own data.';
    }
    if (role === 'Manager') {
      return 'As Manager, you can access your own data and your reportees data.';
    }
    return 'As Employee, you can access only your own data.';
  }

  if (message.includes('reportee')) {
    if (role === 'Manager') {
      return 'You can access your reportees data only.';
    }
    if (role === 'Admin') {
      return 'As Admin, you can access all employees including reportee relationships across the organization.';
    }
    return 'Employees do not have access to other employees or reportees data.';
  }

  if (message.includes('help')) {
    return 'You can ask about leave, attendance, reportees, access rules, and your role-based data.';
  }

  if (message.includes('download') && message.includes('report')) {
    if (role === 'Admin') {
      return 'You can download reports from the relevant Attendance, Leave, Payroll, or Reports module using the Export button.';
    }
    if (role === 'Manager') {
      return 'You can download your team report from the relevant page using the Export button, based on your role access.';
    }
    return 'You can download your report from the relevant page using the Export button available for your role.';
  }

  return 'I understood your question, but the live backend answer is not available right now. I can still help with access rules and role-based HR questions.';
};

const FloatingChatbot = ({ role = 'Default' }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState([]);
  const [isListening, setIsListening] = useState(false);
  const [isVoiceSupported, setIsVoiceSupported] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [showPrompts, setShowPrompts] = useState(true);
  const [launcherAnimation, setLauncherAnimation] = useState(null);
  const [downloadFlow, setDownloadFlow] = useState(null);

  const messagesEndRef = useRef(null);

  const content = useMemo(() => {
    return ROLE_COPY[role] || ROLE_COPY.Default;
  }, [role]);

  useEffect(() => {
    let isMounted = true;

    const loadLauncherAnimation = async () => {
      try {
        const response = await fetch('/robot.json');
        if (!response.ok) {
          throw new Error('Failed to load launcher animation');
        }
        const animationJson = await response.json();
        if (isMounted) {
          setLauncherAnimation(animationJson);
        }
      } catch (error) {
        if (isMounted) {
          setLauncherAnimation(null);
        }
      }
    };

    loadLauncherAnimation();

    return () => {
      isMounted = false;
    };
  }, []);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  useEffect(() => {
    // Check for MediaRecorder support
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      setIsVoiceSupported(true);
    } else {
      setIsVoiceSupported(false);
    }
  }, []);

  const handleVoiceInput = async () => {
    if (isListening) {
      // Stop recording
      if (mediaRecorderRef.current) {
        mediaRecorderRef.current.stop();
      }
      setIsListening(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      // --- SILENCE DETECTION ---
      const audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      
      let lastSpeakTime = Date.now();
      const startTime = Date.now();
      const SILENCE_THRESHOLD = 30; // Increased to ignore background hum/fans
      const SILENCE_DURATION = 1200; // Reduced to 1.2s for faster response
      const MAX_DURATION = 5000; // Safety limit reduced to 5s as requested

      const checkSilence = () => {
        if (mediaRecorder.state !== 'recording') return;

        analyser.getByteFrequencyData(dataArray);
        
        let peak = 0;
        for (let i = 0; i < bufferLength; i++) {
          if (dataArray[i] > peak) peak = dataArray[i];
        }

        if (peak > SILENCE_THRESHOLD) {
          lastSpeakTime = Date.now();
        }

        const elapsed = Date.now() - startTime;
        const silenceElapsed = Date.now() - lastSpeakTime;

        // Stop if silent for 1.5s OR if we hit the 12s total limit
        if (silenceElapsed > SILENCE_DURATION || elapsed > MAX_DURATION) {
          console.log(elapsed > MAX_DURATION ? "Max duration reached" : "Silence detected");
          mediaRecorder.stop();
        } else {
          requestAnimationFrame(checkSilence);
        }
      };
      // -------------------------

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        
        // Cleanup
        audioContext.close();
        stream.getTracks().forEach(track => track.stop());
        setIsListening(false);

        setIsSending(true);
        try {
          const formData = new FormData();
          formData.append('audio', audioBlob, 'voice.webm');

          const response = await api.post('/chatbot/voice/', formData, {
            headers: {
              'Content-Type': 'multipart/form-data',
            },
          });

          const transcript = response.data.transcript;
          if (transcript && transcript.trim()) {
            setMessage(transcript);
          }
        } catch (error) {
          console.error('Transcription error:', error);
          showToast ? showToast('Error', 'error', 'Could not process voice input.') : alert('Could not process voice input.');
        } finally {
          setIsSending(false);
        }
      };

      mediaRecorder.start();
      setIsListening(true);
      checkSilence(); 
    } catch (err) {
      console.error('Microphone access denied:', err);
      showToast ? showToast('Error', 'error', 'Microphone access denied.') : alert('Microphone access denied.');
    }
  };

  useEffect(() => {
    const clearChatState = () => {
      setMessages([]);
      setMessage('');
      setIsOpen(false);
      setShowPrompts(true);
      setDownloadFlow(null);
    };

    const handleStorageChange = () => {
      if (!localStorage.getItem('access_token')) {
        clearChatState();
      }
    };

    if (!localStorage.getItem('access_token')) {
      clearChatState();
    }

    window.addEventListener('storage', handleStorageChange);

    return () => {
      window.removeEventListener('storage', handleStorageChange);
    };
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, showPrompts, isOpen]);

  const sendMessage = async (rawMessage) => {
    if (!rawMessage.trim() || isSending) return;
    const outgoing = rawMessage.trim();
    setShowPrompts(false);
    setMessages((prev) => ([
      ...prev,
      { type: 'user', text: outgoing },
    ]));
    setMessage('');

    setIsSending(true);
    try {
      // Send last 5 messages as history for context
      const history = messages.slice(-5).map((m) => ({
        role: m.type === 'user' ? 'user' : 'assistant',
        text: m.text,
      }));

      const response = await api.post('/chatbot/query/', {
        message: outgoing,
        history,
      });
      const reply = response?.data?.answer || 'I could not generate a response.';
      const action = response?.data?.suggested_action;

      setMessages((prev) => ([
        ...prev,
        { 
          type: 'assistant', 
          text: reply,
          action: action && action !== 'none' ? action : null
        },
      ]));
    } catch (error) {
      const fallbackReply = buildAssistantReply(role, outgoing);
      setMessages((prev) => ([
        ...prev,
        {
          type: 'assistant',
          text: 'Sorry, I do not have enough data to answer that right now.',
        },
      ]));
    } finally {
      setIsSending(false);
    }
  };

  const downloadEmployeeReport = async (employeeId, period) => {
    const params = new URLSearchParams({
      employee_id: employeeId,
      type: period.type,
      ...period.query,
    });

    const response = await api.get(`/generatereport/pdf/?${params.toString()}`, {
      responseType: 'blob',
    });

    const contentDisposition = response.headers?.['content-disposition'];
    let fileName = '';

    if (contentDisposition) {
      const fileNameMatch = contentDisposition.match(/filename=\"?([^"]+)\"?/i);
      if (fileNameMatch?.[1]) {
        fileName = fileNameMatch[1];
      }
    }

    if (!fileName) {
      const suffix = period.query.months || period.query.year || period.label.replace(/\s+/g, '_');
      fileName = `${employeeId}_employee_report_${suffix}.pdf`;
    }

    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', fileName);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const handleDownloadFlowMessage = async (rawMessage) => {
    const outgoing = rawMessage.trim();
    const flow = downloadFlow;
    if (!flow) return false;
    const extracted = extractDownloadReportDetails(outgoing);

    if (looksLikeGeneralQuestion(outgoing)) {
      setDownloadFlow(null);
      await sendMessage(outgoing);
      return true;
    }

    setShowPrompts(false);
    setMessages((prev) => ([
      ...prev,
      { type: 'user', text: outgoing },
    ]));
    setMessage('');

    if (flow.step === 'employeeId') {
      const employeeId = extracted.employeeId || normalizeEmployeeId(outgoing);
      if (!employeeId) {
        setMessages((prev) => ([
          ...prev,
          { type: 'assistant', text: 'Please enter a valid employee ID like EMP001.' },
        ]));
        return true;
      }

      setIsSending(true);
      try {
        // Validation check against the new backend endpoint
        const checkResp = await api.get(`/chatbot/check-employee/?employee_id=${employeeId}`);
        const { name } = checkResp.data;

        // If validation passes, check if they also provided the period in this message
        const period = extracted.period || parseReportPeriod(outgoing);
        
        if (period) {
          await downloadEmployeeReport(employeeId, period);
          setMessages((prev) => ([
            ...prev,
            { type: 'assistant', text: `Found ${name}. Downloading report for ${period.label}...` },
          ]));
          setDownloadFlow(null);
        } else {
          setDownloadFlow({ step: 'period', employeeId });
          setMessages((prev) => ([
            ...prev,
            { type: 'assistant', text: `Found ${name}. Please enter the month/period (e.g. March 2026, current month).` },
          ]));
        }
      } catch (error) {
        const errorMsg = error?.response?.data?.error || `This employee (${employeeId}) is not available. Please check the ID and try again.`;
        setMessages((prev) => ([
          ...prev,
          { type: 'assistant', text: errorMsg },
        ]));
        // Keep them on employeeId step to retry
      } finally {
        setIsSending(false);
      }
      return true;
    }

    if (flow.step === 'period') {
      const period = extracted.period || parseReportPeriod(outgoing);
      if (!period) {
        setMessages((prev) => ([
          ...prev,
          {
            type: 'assistant',
            text: 'Please enter a valid period like current week, last week, current month, March 2026, or 2026.',
          },
        ]));
        return true;
      }

      setIsSending(true);
      try {
        await downloadEmployeeReport(flow.employeeId, period);
        setMessages((prev) => ([
          ...prev,
          {
            type: 'assistant',
            text: `Downloading report for ${flow.employeeId} for ${period.label}.`,
          },
        ]));
      } catch (error) {
        setMessages((prev) => ([
          ...prev,
          { type: 'assistant', text: 'Failed to download report. Please try again.' },
        ]));
      } finally {
        setIsSending(false);
        setDownloadFlow(null);
      }
      return true;
    }

    return false;
  };

  const handlePromptClick = (prompt) => {
    const normalizedPrompt = prompt.toLowerCase();
    if (normalizedPrompt.includes('download') && normalizedPrompt.includes('report')) {
      setShowPrompts(false);
      setDownloadFlow({ step: 'employeeId', employeeId: '' });
      setMessages((prev) => ([
        ...prev,
        { type: 'user', text: prompt },
        { type: 'assistant', text: 'Please enter the Employee ID and the Month (e.g., EMP001 current month).' },
      ]));
      return;
    }
    sendMessage(prompt);
  };

  const handleSend = async () => {
    if (downloadFlow) {
      await handleDownloadFlowMessage(message);
      return;
    }

    const input = message.trim().toLowerCase();
    if (input.includes('download') && input.includes('report')) {
      setShowPrompts(false);
      const extracted = extractDownloadReportDetails(input);
      if (extracted.employeeId && extracted.period) {
        setMessages((prev) => ([...prev, { type: 'user', text: message.trim() }]));
        setMessage('');
        setIsSending(true);
        try {
          await downloadEmployeeReport(extracted.employeeId, extracted.period);
          setMessages((prev) => ([
            ...prev,
            { type: 'assistant', text: `Downloading report for ${extracted.employeeId} for ${extracted.period.label}.` },
          ]));
        } catch (error) {
           setMessages((prev) => ([...prev, { type: 'assistant', text: 'I could not download that report. Please check the ID and try again.' }]));
        } finally {
          setIsSending(false);
        }
        return;
      }

      if (extracted.employeeId) {
        setMessages((prev) => ([
          ...prev, 
          { type: 'user', text: message.trim() },
          { type: 'assistant', text: `Employee ID noted as ${extracted.employeeId}. Please enter the period (e.g., current month, March 2026).` }
        ]));
        setMessage('');
        setDownloadFlow({ step: 'period', employeeId: extracted.employeeId });
        return;
      }

      setMessages((prev) => ([
        ...prev,
        { type: 'user', text: message.trim() },
        { type: 'assistant', text: 'Please enter the employee ID for the report.' }
      ]));
      setMessage('');
      setDownloadFlow({ step: 'employeeId', employeeId: '' });
      return;
    }

    await sendMessage(message);
  };



  const handleDeleteChat = async () => {
    const result = await Swal.fire({
      title: 'Delete Chat?',
      text: 'Are you sure you want to clear this chat conversation?',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#4f46e5',
      cancelButtonColor: '#d33',
      confirmButtonText: 'Yes, Delete',
      cancelButtonText: 'Cancel',
    });

    if (!result.isConfirmed) return;

    setMessages([]);
    setMessage('');
    setShowPrompts(true);
    setDownloadFlow(null);
  };

  const chatbotPanel = isOpen ? (
    <div
      className="floating-chatbot-modal-layer"
      onClick={() => setIsOpen(false)}
      role="presentation"
    >
      <div
        className="floating-chatbot-panel"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={content.title}
      >
          <div className="floating-chatbot-header">
            <div className="floating-chatbot-brand">
              <div className="floating-chatbot-avatar">
                <HiOutlineSparkles />
              </div>
              <div>
                <h3>{content.title}</h3>
              </div>
            </div>
            <div className="floating-chatbot-header-actions">
              <button
                type="button"
                className="floating-chatbot-icon-btn"
                onClick={handleDeleteChat}
                aria-label="Delete chat"
                title="Delete chat"
              >
                <HiOutlineArrowPath />
              </button>
              <button
                type="button"
                className="floating-chatbot-close"
                onClick={() => setIsOpen(false)}
                aria-label="Close chatbot"
              >
                <FaTimes />
              </button>
            </div>
          </div>

          <div className="floating-chatbot-body">
            {messages.length === 0 ? (
              <div className="floating-chatbot-empty">
                <div className="floating-chatbot-empty-anim">
                  <HiOutlineChatBubbleLeftRight />
                </div>
                <span>Ask me something.</span>
                <small>Try a quick question below or ask about attendance, leave, approvals, or reports.</small>
              </div>
            ) : (
              <div className="floating-chatbot-messages">
                {messages.map((item, index) => (
                  <div
                    key={`${item.type}-${index}`}
                    className={`floating-chatbot-message ${item.type}`}
                  >
                    <div className="floating-chatbot-message-text">{item.text}</div>
                    {item.action && (
                      <button
                        type="button"
                        className="floating-chatbot-action-btn"
                        onClick={() => {
                          if (item.action.startsWith('/')) {
                            window.location.href = item.action;
                          }
                        }}
                      >
                         Open {item.action.replace('/', '').charAt(0).toUpperCase() + item.action.slice(2)}
                      </button>
                      )}
                    </div>
                ))}
                {isSending && (
                  <div className="floating-chatbot-typing-container">
                    <div className="floating-chatbot-message assistant floating-chatbot-typing">
                      <span className="floating-chatbot-typing-dot" />
                      <span className="floating-chatbot-typing-dot" />
                      <span className="floating-chatbot-typing-dot" />
                    </div>
                  </div>
                )}
              </div>
            )}

            {messages.length > 0 && (
              <button
                type="button"
                className="floating-chatbot-suggestions-toggle"
                onClick={() => setShowPrompts((prev) => !prev)}
              >
                {showPrompts ? 'Hide suggestions' : 'Show suggestions'}
              </button>
            )}

            {showPrompts && (
              <div className="floating-chatbot-prompts">
                {content.prompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    className="floating-chatbot-prompt"
                    onClick={() => handlePromptClick(prompt)}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="floating-chatbot-footer">
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={
                downloadFlow?.step === 'employeeId'
                  ? 'Enter employee ID or ask another question...'
                  : downloadFlow?.step === 'period'
                    ? 'Enter period like current month or ask another question...'
                    : 'Type your question...'
              }
              className="floating-chatbot-input"
              disabled={isSending}
            />
            {isVoiceSupported && (
              <button
                type="button"
                className={`floating-chatbot-voice ${isListening ? 'listening' : ''}`}
                onClick={handleVoiceInput}
                aria-label="Voice input"
                disabled={isSending}
              >
                <HiOutlineMicrophone />
              </button>
            )}
            <button
              type="button"
              className="floating-chatbot-send"
              onClick={handleSend}
              aria-label="Send message"
              disabled={isSending}
            >
              <FaPaperPlane />
            </button>
          </div>
      </div>
    </div>
  ) : null;

  return (
    <>
      {isOpen && createPortal(chatbotPanel, document.body)}

      {!isOpen && (
        <button
          type="button"
          className="floating-chatbot-launcher"
          onClick={() => setIsOpen((prev) => !prev)}
          aria-label="Open chatbot"
        >
          {launcherAnimation ? (
            <Lottie
              animationData={launcherAnimation}
              loop
              autoplay
              className="floating-chatbot-launcher-lottie"
            />
          ) : (
            <HiOutlineChatBubbleLeftRight />
          )}
        </button>
      )}
    </>
  );
};

export default FloatingChatbot;
