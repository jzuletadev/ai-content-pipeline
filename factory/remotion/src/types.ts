export type Animation = "fade_in" | "slide_up" | "typewriter" | "zoom_in";

export type Scene = {
  text: string;
  startFrame: number;
  endFrame: number;
  animation: Animation;
  imagePath: string | null;
};

export type Style = {
  color_primary?: string;
  color_shadow?: string;
  font?: string;
  mood?: string;
};

export type VideoSpec = {
  scenes: Scene[];
  audioPath: string | null;
  style: Style;
};
