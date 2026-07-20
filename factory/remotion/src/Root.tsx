import React from "react";
import { Composition } from "remotion";
import { MainVideo } from "./MainVideo";
import type { VideoSpec } from "./types";

const defaultProps: VideoSpec = {
  scenes: [],
  audioPath: null,
  style: {},
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="MainVideo"
      component={MainVideo}
      durationInFrames={300}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={defaultProps}
      calculateMetadata={({ props }) => {
        const scenes = props.scenes ?? [];
        const durationInFrames = scenes.length
          ? Math.max(...scenes.map((s) => s.endFrame))
          : 300;
        return { durationInFrames };
      }}
    />
  );
};
