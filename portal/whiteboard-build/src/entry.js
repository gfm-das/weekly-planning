// The whiteboard's vendored bundle: Excalidraw 0.18.1 and React 19, built once with Vite (see ../README.md) into
// portal/whiteboard/vendor/. The page's own code (portal/whiteboard/whiteboard.js) imports what it needs from here,
// so changing the page never needs a rebuild. Only libraries, no mission logic.
import * as React from 'react'
import { createRoot } from 'react-dom/client'
import '@excalidraw/excalidraw/index.css'

export { React, createRoot }
export {
  CaptureUpdateAction,
  Excalidraw,
  Footer,
  FONT_FAMILY,
  MainMenu,
  THEME,
  WelcomeScreen,
  convertToExcalidrawElements,
  exportToBlob,
  getCommonBounds,
  getSceneVersion,
  hashElementsVersion,
  languages,
  newElementWith,
  restore,
  restoreAppState,
  restoreElements,
  sceneCoordsToViewportCoords,
  serializeAsJSON,
  viewportCoordsToSceneCoords,
} from '@excalidraw/excalidraw'

export const VERSIONS = { excalidraw: '0.18.1', react: React.version }
