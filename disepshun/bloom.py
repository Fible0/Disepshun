"""Multi-scale neon bloom.

The scene is rendered with the glow mask in its alpha channel. The masked colour
is downsampled through a chain of progressively smaller buffers and upsampled
back, adding every level on the way up. Small levels give a wide, faint haze and
large levels a tight bright rim, so the halo fades out smoothly instead of
ending in a hard band.
"""
from direct.filter.FilterManager import FilterManager
from panda3d.core import AuxBitplaneAttrib, Shader, Texture, Vec2

VERTEX = """#version 120
uniform mat4 p3d_ModelViewProjectionMatrix;
attribute vec4 p3d_Vertex;
varying vec2 uv;
void main() {
    gl_Position=p3d_ModelViewProjectionMatrix*p3d_Vertex;
    uv=p3d_Vertex.xz*.5+.5;
}
"""

# Turn glowing pixels into their full-brightness hue so halos keep the same
# colour and strength no matter how a face is shaded.
PREFILTER = """#version 120
uniform sampler2D src;
uniform vec2 src_scale;
uniform vec2 src_texel;
varying vec2 uv;
vec3 hue(vec2 p) {
    vec4 c=texture2D(src,p*src_scale);
    float peak=max(max(c.r,c.g),c.b);
    return c.rgb/max(peak,.05)*smoothstep(.55,.85,c.a);
}
void main() {
    vec2 o=src_texel*.5;
    vec3 c=hue(uv+vec2(-o.x,-o.y))+hue(uv+vec2(o.x,-o.y))+hue(uv+vec2(-o.x,o.y))+hue(uv+vec2(o.x,o.y));
    gl_FragColor=vec4(c*.25,1.0);
}
"""

# Dual-filter (Kawase) downsample.
DOWN = """#version 120
uniform sampler2D src;
uniform vec2 src_scale;
uniform vec2 src_texel;
varying vec2 uv;
vec3 s(vec2 p) { return texture2D(src,p*src_scale).rgb; }
void main() {
    vec2 o=src_texel;
    vec3 c=s(uv)*4.0+s(uv+vec2(-o.x,-o.y))+s(uv+vec2(o.x,-o.y))+s(uv+vec2(-o.x,o.y))+s(uv+vec2(o.x,o.y));
    gl_FragColor=vec4(c/8.0,1.0);
}
"""

# Dual-filter (Kawase) upsample of the smaller level, plus this level's detail.
UP = """#version 120
uniform sampler2D src;
uniform vec2 src_scale;
uniform vec2 src_texel;
uniform sampler2D detail;
uniform vec2 detail_scale;
varying vec2 uv;
vec3 s(vec2 p) { return texture2D(src,p*src_scale).rgb; }
void main() {
    vec2 o=src_texel;
    vec3 c=s(uv+vec2(-o.x*2.0,0.0))+s(uv+vec2(o.x*2.0,0.0))+s(uv+vec2(0.0,-o.y*2.0))+s(uv+vec2(0.0,o.y*2.0))
          +(s(uv+vec2(-o.x,-o.y))+s(uv+vec2(o.x,-o.y))+s(uv+vec2(-o.x,o.y))+s(uv+vec2(o.x,o.y)))*2.0;
    gl_FragColor=vec4(c/12.0+texture2D(detail,uv*detail_scale).rgb,1.0);
}
"""

COMPOSITE = """#version 120
uniform sampler2D scene;
uniform vec2 scene_scale;
uniform sampler2D bloom;
uniform vec2 bloom_scale;
uniform vec2 bloom_texel;
uniform float intensity;
varying vec2 uv;
void main() {
    vec4 base=texture2D(scene,uv*scene_scale);
    // The shader generator writes .5 alpha for ordinary surfaces and 1 for glowing ones.
    float core=smoothstep(.55,.85,base.a);
    vec2 o=bloom_texel*.5;
    vec3 b=(texture2D(bloom,(uv+vec2(-o.x,-o.y))*bloom_scale).rgb+texture2D(bloom,(uv+vec2(o.x,-o.y))*bloom_scale).rgb
           +texture2D(bloom,(uv+vec2(-o.x,o.y))*bloom_scale).rgb+texture2D(bloom,(uv+vec2(o.x,o.y))*bloom_scale).rgb)*.25;
    // Glowing faces get a little inner light, but most of the halo goes around them.
    float peak=max(max(base.r,base.g),base.b);
    vec3 surface=base.rgb+base.rgb/max(peak,.05)*core*.08;
    vec3 halo=1.0-exp(-b*intensity*mix(1.0,.15,core));
    // Screen blend: halos brighten without clipping into flat bands.
    gl_FragColor=vec4(1.0-(1.0-clamp(surface,0.0,1.0))*(1.0-halo),1.0);
}
"""

LEVELS = 6  # Buffer divisors 2, 4, 8, 16, 32, 64.


class NeonBloom:
    def __init__(self, win, cam, intensity=5.0):
        self.manager = FilterManager(win, cam)
        self.passes = []  # (quad, {input name: texture})
        self.input_sizes = {}
        self.ok = False
        scene = self.texture('neon-scene')
        self.final = self.manager.renderSceneInto(colortex=scene, auxbits=AuxBitplaneAttrib.ABOGlow)
        if self.final is None: return
        down = []
        source, shader = scene, PREFILTER
        for level in range(LEVELS):
            tex = self.texture(f'neon-down{level}')
            quad = self.manager.renderQuadInto(f'neon-down{level}', colortex=tex, div=2 ** (level + 1))
            if quad is None: return
            self.add_pass(quad, shader, src=source)
            down.append(tex); source, shader = tex, DOWN
        for level in range(LEVELS - 2, -1, -1):
            tex = self.texture(f'neon-up{level}')
            quad = self.manager.renderQuadInto(f'neon-up{level}', colortex=tex, div=2 ** (level + 1))
            if quad is None: return
            self.add_pass(quad, UP, src=source, detail=down[level])
            source = tex
        self.add_pass(self.final, COMPOSITE, scene=scene, bloom=source)
        self.final.setShaderInput('intensity', intensity / LEVELS * 2.0)
        self.ok = True
        self.update()

    @staticmethod
    def texture(name):
        tex = Texture(name)
        tex.setWrapU(Texture.WMClamp); tex.setWrapV(Texture.WMClamp)
        tex.setMinfilter(Texture.FTLinear); tex.setMagfilter(Texture.FTLinear)
        return tex

    def add_pass(self, quad, source, **inputs):
        quad.setShader(Shader.make(Shader.SL_GLSL, vertex=VERTEX, fragment=source))
        for name, tex in inputs.items(): quad.setShaderInput(name, tex)
        self.passes.append((quad, inputs))

    def update(self):
        """Padded buffers change their texture scale and size on resize."""
        for quad, inputs in self.passes:
            for name, tex in inputs.items():
                scale = tex.getTexScale()
                padx, pady = max(tex.getXSize(), 1), max(tex.getYSize(), 1)
                key = (quad, name)
                size = (scale.x, scale.y, padx, pady)
                if self.input_sizes.get(key) == size: continue
                self.input_sizes[key] = size
                quad.setShaderInput(name + '_scale', Vec2(scale.x, scale.y))
                # Texel size in the shaders' unpadded 0..1 coordinates.
                quad.setShaderInput(name + '_texel', Vec2(1.0 / (padx * max(scale.x, 1e-6)), 1.0 / (pady * max(scale.y, 1e-6))))

    def cleanup(self):
        self.manager.cleanup()
        self.passes = []
        self.input_sizes.clear()
