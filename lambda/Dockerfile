# Lambda container image for video generation
FROM public.ecr.aws/lambda/python:3.12

# Install FFmpeg
RUN dnf install -y \
    tar \
    xz \
    && dnf clean all

# Download and install static FFmpeg binary
RUN curl -L -o /tmp/ffmpeg.tar.xz https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz \
    && cd /tmp \
    && tar -xf ffmpeg.tar.xz \
    && mv ffmpeg-*-amd64-static/ffmpeg /usr/local/bin/ \
    && chmod +x /usr/local/bin/ffmpeg \
    && rm -rf /tmp/ffmpeg* \
    && ffmpeg -version

# Install fonts
RUN dnf install -y dejavu-sans-fonts && dnf clean all

# Set FFmpeg path for imageio
ENV IMAGEIO_FFMPEG_EXE=/usr/local/bin/ffmpeg

# Copy requirements and install Python dependencies
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
COPY video_generator.py ${LAMBDA_TASK_ROOT}/

# Set the handler
CMD ["lambda_function.handler"]
