import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import { 
  Play, 
  Bug, 
  CheckCircle2, 
  XCircle, 
  TerminalSquare, 
  Cpu, 
  Code2, 
  RotateCcw,
  ArrowRightLeft,
  ChevronDown
} from "lucide-react";
import clsx from "clsx";

const API_URL = "http://localhost:8000";

// Templates are now empty to ensure the user starts with a clean slate
const TEMPLATES = {
  python: "",
  javascript: "",
  cpp: ""
};

// --- Custom Lightweight Editor Components ---

const SimpleEditor = ({ value, onChange, readOnly = false }) => {
  const textareaRef = useRef(null);
  const linesRef = useRef(null);

  // Synchronize scrolling between textarea and line numbers
  const handleScroll = () => {
    if (textareaRef.current && linesRef.current) {
      linesRef.current.scrollTop = textareaRef.current.scrollTop;
    }
  };

  const lineCount = value.split("\n").length;
  const lines = Array.from({ length: lineCount }, (_, i) => i + 1);

  return (
    <div className="flex h-full w-full bg-[#1e1e1e] font-mono text-sm relative">
      {/* Line Numbers Gutter */}
      <div 
        ref={linesRef}
        className="bg-[#1e1e1e] text-gray-500 text-right pr-4 py-4 w-12 select-none border-r border-[#333] leading-relaxed overflow-hidden"
        style={{ fontFamily: '"Fira Code", "Consolas", monospace' }}
      >
        {lines.map((n) => (
          <div key={n}>{n}</div>
        ))}
      </div>
      
      {/* Code Input Area */}
      <textarea
        ref={textareaRef}
        onScroll={handleScroll}
        value={value}
        onChange={(e) => onChange && onChange(e.target.value)}
        readOnly={readOnly}
        spellCheck={false}
        placeholder="Write your code here..."
        // whitespace-pre ensures text doesn't wrap, keeping lines aligned with numbers
        className="flex-1 h-full bg-[#1e1e1e] text-gray-300 p-4 resize-none outline-none border-none leading-relaxed whitespace-pre placeholder-gray-600"
        style={{ fontFamily: '"Fira Code", "Consolas", monospace' }}
      />
    </div>
  );
};

const SimpleDiffView = ({ original, modified }) => {
  return (
    <div className="flex h-full w-full">
      <div className="flex-1 flex flex-col border-r border-[#333]">
        <div className="bg-red-900/20 text-red-200 text-xs px-2 py-1 font-mono border-b border-red-900/30 text-center">
          Original (Buggy)
        </div>
        <SimpleEditor value={original} readOnly={true} />
      </div>
      <div className="flex-1 flex flex-col">
        <div className="bg-green-900/20 text-green-200 text-xs px-2 py-1 font-mono border-b border-green-900/30 text-center">
          AI Fix (Proposed)
        </div>
        <SimpleEditor value={modified} readOnly={true} />
      </div>
    </div>
  );
};

// --- Main Application ---

export default function App() {
  // State
  const [language, setLanguage] = useState("python");
  const [code, setCode] = useState(""); // Initialize with empty code
  const [output, setOutput] = useState("Ready to execute...");
  const [analysis, setAnalysis] = useState("");
  const [fixedCode, setFixedCode] = useState("");
  
  // UI State
  const [mode, setMode] = useState("edit"); // 'edit' | 'diff'
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState("");
  const [activeTab, setActiveTab] = useState("terminal"); // 'terminal' | 'analysis'

  const handleLanguageChange = (e) => {
    const newLang = e.target.value;
    setLanguage(newLang);
    setCode(""); // Clear code on language switch
    setOutput("Language switched. Ready.");
    setMode("edit");
  };

  // --- Actions ---

  const handleRun = async () => {
    if (!code.trim()) {
      setOutput("⚠️ Editor is empty. Please write some code first.");
      return;
    }

    setLoading(true);
    setLoadingMsg(`Compiling & Running ${language} code...`);
    setActiveTab("terminal");
    
    try {
      const res = await axios.post(`${API_URL}/run`, { 
        code, 
        language 
      });
      setOutput(res.data.logs || "No output returned.");
    } catch (err) {
      setOutput(`System Error: ${err.message}\nCheck if backend is running.`);
    } finally {
      setLoading(false);
    }
  };

  const handleDebug = async () => {
    if (!code.trim()) {
      setOutput("⚠️ Cannot debug empty code.");
      return;
    }

    setLoading(true);
    setLoadingMsg(`AI is analyzing ${language} stack traces...`);
    
    try {
      const res = await axios.post(`${API_URL}/debug`, {
        code,
        language, // Sending dynamic language
        logs: output,
        model: "qwen2.5-coder"
      });

      setFixedCode(res.data.fixed_code);
      setAnalysis(res.data.analysis);
      setMode("diff"); 
      setActiveTab("analysis"); 
    } catch (err) {
      setOutput(`AI Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const applyFix = () => {
    setCode(fixedCode);
    setMode("edit");
    setOutput("Fix applied. Run the code to verify.");
    setActiveTab("terminal");
  };

  const rejectFix = () => {
    setMode("edit");
    setOutput("Fix rejected. Restored original code.");
  };

  return (
    <div className="h-screen flex flex-col bg-[#1e1e1e] text-gray-300 font-sans overflow-hidden">
      
      {/* --- Header / Toolbar --- */}
      <header className="h-14 border-b border-[#333] bg-[#252526] flex items-center px-4 justify-between shadow-md z-10">
        <div className="flex items-center gap-3">
          <div className="bg-blue-600 p-1.5 rounded-lg">
            <Cpu className="w-5 h-5 text-white" />
          </div>
          <h1 className="font-bold text-gray-100 tracking-wide hidden md:block">
            Fixpoint
          </h1>
          
          {/* Language Selector */}
          <div className="relative group ml-4">
            <select 
              value={language}
              onChange={handleLanguageChange}
              className="appearance-none bg-[#1e1e1e] border border-[#333] text-gray-300 px-3 py-1.5 pr-8 rounded text-sm focus:outline-none focus:border-blue-500 cursor-pointer hover:bg-[#2d2d2d] transition-colors"
            >
              <option value="python">Python</option>
              <option value="javascript">JavaScript (Node)</option>
              <option value="cpp">C++ (GCC)</option>
            </select>
            <ChevronDown className="w-4 h-4 text-gray-500 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>
        </div>

        <div className="flex items-center gap-3">
          {mode === "edit" ? (
            <>
              <button 
                onClick={handleRun}
                disabled={loading}
                className="flex items-center gap-2 px-4 py-1.5 bg-[#2d2d2d] hover:bg-green-700 hover:text-white text-green-400 border border-green-900/30 rounded transition-all text-sm font-medium disabled:opacity-50"
              >
                <Play className="w-4 h-4 fill-current" /> Run
              </button>
              <button 
                onClick={handleDebug}
                disabled={loading}
                className="flex items-center gap-2 px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded shadow-lg shadow-blue-900/20 transition-all text-sm font-medium disabled:opacity-50"
              >
                {loading ? <RotateCcw className="w-4 h-4 animate-spin" /> : <Bug className="w-4 h-4" />}
                Auto Debug
              </button>
            </>
          ) : (
            <>
               <span className="text-xs text-gray-400 mr-2 flex items-center gap-1">
                 <ArrowRightLeft className="w-3 h-3" /> Diff View
               </span>
              <button 
                onClick={applyFix}
                className="flex items-center gap-2 px-4 py-1.5 bg-green-600 hover:bg-green-500 text-white rounded shadow-lg text-sm font-medium"
              >
                <CheckCircle2 className="w-4 h-4" /> Apply
              </button>
              <button 
                onClick={rejectFix}
                className="flex items-center gap-2 px-4 py-1.5 bg-[#2d2d2d] hover:bg-red-900/50 text-red-400 border border-red-900/30 rounded transition-all text-sm font-medium"
              >
                <XCircle className="w-4 h-4" /> Cancel
              </button>
            </>
          )}
        </div>
      </header>

      {/* --- Main Workspace --- */}
      <div className="flex-1 flex flex-col relative">
        
        {/* Loading Overlay */}
        {loading && (
          <div className="absolute inset-0 bg-[#1e1e1e]/80 backdrop-blur-sm z-50 flex flex-col items-center justify-center">
            <div className="flex flex-col items-center gap-4 p-8 bg-[#252526] rounded-xl border border-[#333] shadow-2xl">
              <RotateCcw className="w-10 h-10 text-blue-500 animate-spin" />
              <p className="text-lg font-medium text-gray-200 animate-pulse">{loadingMsg}</p>
            </div>
          </div>
        )}

        {/* Editor Area */}
        <div className="flex-1 relative overflow-hidden">
          {mode === "edit" ? (
            <SimpleEditor 
              value={code} 
              onChange={setCode} 
            />
          ) : (
            <SimpleDiffView 
              original={code} 
              modified={fixedCode} 
            />
          )}
        </div>

        {/* --- Bottom Panel (Terminal / Analysis) --- */}
        <div className="h-64 bg-[#1e1e1e] border-t border-[#333] flex flex-col">
          <div className="flex border-b border-[#333] bg-[#252526]">
            <button 
              onClick={() => setActiveTab("terminal")}
              className={clsx(
                "px-4 py-2 text-xs font-medium uppercase tracking-wider flex items-center gap-2 border-r border-[#333] transition-colors",
                activeTab === "terminal" ? "bg-[#1e1e1e] text-white border-t-2 border-t-blue-500" : "text-gray-500 hover:bg-[#2d2d2d]"
              )}
            >
              <TerminalSquare className="w-4 h-4" /> Terminal
            </button>
            <button 
              onClick={() => setActiveTab("analysis")}
              className={clsx(
                "px-4 py-2 text-xs font-medium uppercase tracking-wider flex items-center gap-2 border-r border-[#333] transition-colors",
                activeTab === "analysis" ? "bg-[#1e1e1e] text-blue-400 border-t-2 border-t-blue-500" : "text-gray-500 hover:bg-[#2d2d2d]"
              )}
            >
              <Code2 className="w-4 h-4" /> AI Analysis
            </button>
          </div>

          <div className="flex-1 overflow-auto p-0 font-mono text-sm">
            {activeTab === "terminal" && (
              <div className="p-4 text-gray-300 whitespace-pre-wrap">
                {output ? output : <span className="text-gray-600 italic">No output yet. Click 'Run Code' to start.</span>}
              </div>
            )}

            {activeTab === "analysis" && (
              <div className="p-4 bg-[#1e1e1e] h-full overflow-y-auto">
                {analysis ? (
                  <div className="prose prose-invert max-w-none">
                    <h3 className="text-blue-400 font-bold text-sm mb-2 flex items-center gap-2">
                      <Bug className="w-4 h-4" /> Diagnosis
                    </h3>
                    <p className="text-gray-300 leading-relaxed whitespace-pre-line">{analysis}</p>
                    {mode === "diff" && (
                      <div className="mt-4 p-3 bg-blue-900/20 border border-blue-800/50 rounded text-blue-200 text-xs">
                        <span className="font-bold">Tip:</span> Review the changes in the split view above. Click "Apply" to accept them.
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-gray-600 gap-2 opacity-50">
                    <Bug className="w-8 h-8" />
                    <p>Run the Auto-Debugger to see AI Analysis here.</p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

      </div>
      
      {/* Footer Status Bar */}
      <div className="h-6 bg-[#007acc] text-white text-[10px] flex items-center px-3 justify-between select-none">
        <div className="flex items-center gap-4">
          <span className="uppercase">{language} Environment</span>
          <span>Docker Sandbox</span>
        </div>
        <div className="flex items-center gap-4">
          <span>Ln 1, Col 1</span>
          <span>UTF-8</span>
          <span className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-green-400"></div>
            Online
          </span>
        </div>
      </div>

    </div>
  );
}

