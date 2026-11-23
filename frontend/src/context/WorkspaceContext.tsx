import React, { createContext, useContext, useState } from 'react';

export interface WorkspaceState {
  activeProjectId: string;
  setActiveProjectId: (id: string) => void;
  selectedClipId: string;
  setSelectedClipId: (id: string) => void;
}

const WorkspaceContext = createContext<WorkspaceState>({
  activeProjectId: '',
  setActiveProjectId: () => {},
  selectedClipId: '',
  setSelectedClipId: () => {},
});

const LS_KEY = 'cf_active_project_id';

export const WorkspaceProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeProjectId, setActiveProjectIdState] = useState<string>(
    () => localStorage.getItem(LS_KEY) ?? ''
  );
  const [selectedClipId, setSelectedClipId] = useState('');

  const setActiveProjectId = (id: string) => {
    setActiveProjectIdState(id);
    if (id) {
      localStorage.setItem(LS_KEY, id);
    } else {
      localStorage.removeItem(LS_KEY);
    }
  };

  return (
    <WorkspaceContext.Provider
      value={{ activeProjectId, setActiveProjectId, selectedClipId, setSelectedClipId }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
};

export function useWorkspace(): WorkspaceState {
  return useContext(WorkspaceContext);
}
