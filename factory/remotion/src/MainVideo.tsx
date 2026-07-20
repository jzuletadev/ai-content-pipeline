import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  staticFile,
  useCurrentFrame,
  interpolate,
} from "remotion";
import type { VideoSpec, Scene } from "./types";

const FADE_FRAMES = 12;

export const MainVideo: React.FC<VideoSpec> = ({ scenes, audioPath, style }) => {
  const primary = style.color_primary || "#FFFFFF";
  const shadow = style.color_shadow || "#000000";
  const font = style.font || "Montserrat, sans-serif";

  return (
    <AbsoluteFill style={{ backgroundColor: "#000000" }}>
      {audioPath && <Audio src={staticFile(audioPath)} />}
      {scenes.map((scene, i) => (
        <Sequence
          key={i}
          from={scene.startFrame}
          durationInFrames={Math.max(scene.endFrame - scene.startFrame, 1)}
        >
          <SceneLayer scene={scene} index={i} primary={primary} shadow={shadow} font={font} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};

const SceneLayer: React.FC<{
  scene: Scene;
  index: number;
  primary: string;
  shadow: string;
  font: string;
}> = ({ scene, index, primary, shadow, font }) => {
  const frame = useCurrentFrame();
  const sceneLength = Math.max(scene.endFrame - scene.startFrame, 1);

  // Ken Burns continuo durante TODA la escena (no solo los primeros frames).
  // Alterna dirección de zoom por escena para que no se sienta repetitivo.
  const zoomingIn = index % 2 === 0;
  const scale = interpolate(
    frame,
    [0, sceneLength],
    zoomingIn ? [1, 1.18] : [1.18, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const panX = interpolate(
    frame,
    [0, sceneLength],
    zoomingIn ? [0, -25] : [25, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  // Fade a negro en la entrada y salida de cada escena — transición más suave que el corte duro.
  const fadeIn = interpolate(frame, [0, FADE_FRAMES], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [sceneLength - FADE_FRAMES, sceneLength], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const imageOpacity = Math.min(fadeIn, fadeOut);

  // Animación del texto según lo que definió el guion (Claude).
  let textTransform = "none";
  if (scene.animation === "slide_up") {
    textTransform = `translateY(${interpolate(frame, [0, FADE_FRAMES], [40, 0], {
      extrapolateRight: "clamp",
    })}px)`;
  } else if (scene.animation === "zoom_in") {
    textTransform = `scale(${interpolate(frame, [0, FADE_FRAMES], [0.85, 1], {
      extrapolateRight: "clamp",
    })})`;
  }

  return (
    <AbsoluteFill>
      {scene.imagePath ? (
        <Img
          src={staticFile(scene.imagePath)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${scale}) translateX(${panX}px)`,
            opacity: imageOpacity,
          }}
        />
      ) : (
        <AbsoluteFill style={{ backgroundColor: "#1a1a1a", opacity: imageOpacity }} />
      )}
      {scene.text && (
        <AbsoluteFill
          style={{
            justifyContent: "flex-end",
            alignItems: "center",
            paddingBottom: 140,
            opacity: fadeIn,
          }}
        >
          <div
            style={{
              fontFamily: font,
              // Subtítulos de narración son oraciones largas — texto más chico,
              // fondo detrás para legibilidad (a diferencia de la letra de canción,
              // que son líneas cortas y grandes sin fondo).
              fontSize: scene.text.length > 90 ? 38 : scene.text.length > 45 ? 48 : 64,
              fontWeight: 700,
              color: primary,
              textShadow: `0 0 20px ${shadow}, 2px 2px 8px ${shadow}`,
              textAlign: "center",
              maxWidth: "88%",
              lineHeight: 1.35,
              padding: "16px 28px",
              borderRadius: 12,
              backgroundColor: scene.text.length > 45 ? "rgba(0,0,0,0.45)" : "transparent",
              transform: textTransform,
            }}
          >
            {scene.text}
          </div>
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};
