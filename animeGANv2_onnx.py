# 导入onnxruntime库用于执行ONNX模型
import onnxruntime as ort
# 导入time库用于计时，cv2库用于图像处理
import time, cv2
# 导入numpy库，用于处理数组和进行数学运算
import numpy as np

# 定义process_image函数，用于处理图像，可选择是否将图像大小调整为32的倍数
def process_image(img, x32=True):
    # 获取图像的高度和宽度
    h, w = img.shape[:2]
    # 如果启用x32，将图像大小调整为32的倍数
    if x32:
        # 内部函数to_32s，用于计算大于等于256且为32的倍数的尺寸
        def to_32s(x):
            return 256 if x < 256 else x - x % 32
        # 调整图像大小
        img = cv2.resize(img, (to_32s(w), to_32s(h)))
    # 将图像颜色空间从BGR转换为RGB，转换为float32类型，并进行归一化
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 127.5 - 1.0
    return img

# 定义load_test_data函数，用于加载测试数据，接受图像和大小参数
def load_test_data(img0, size):
    # 调用process_image函数处理图像
    img = process_image(img0, size)
    # 增加一个新的维度，用于模型输入
    img = np.expand_dims(img, axis=0)
    return img, img0.shape

# 定义show_images函数，用于显示图像，接受图像和大小参数
def show_images(images, size):
    # 对图像进行反归一化操作，并确保像素值在0到255之间
    images = (np.squeeze(images) + 1.) / 2 * 255
    images = np.clip(images, 0, 255).astype(np.uint8)
    # 调整图像大小并将颜色空间从RGB转换回BGR
    images = cv2.resize(images, size)
    images = cv2.cvtColor(images, cv2.COLOR_RGB2BGR)
    return images

# 当脚本作为主程序运行时执行以下代码
if __name__ == '__main__':
    # 指定ONNX模型文件路径
    onnx_file = 'Shinkai_53.onnx'
    # 创建一个ONNX运行时会话，指定使用CUDA和CPU作为后端
    session = ort.InferenceSession(onnx_file, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    # 获取模型的输入和输出节点的名称
    x = session.get_inputs()[0].name
    y = session.get_outputs()[0].name
    # 设置运行模式，1为图像处理，2为视频流处理
    mode = 1
    # 如果模式为1，处理单个图像
    if mode == 1:
        # 指定要处理的图像路径
        image_path = "AE86.jpg"
        # 读取图像文件
        image = cv2.imread(image_path)
        # 加载测试数据，并获取图像的原始尺寸
        sample_image, shape = load_test_data(image, size=[256, 256])
        # 使用模型进行推断
        fake_img = session.run(None, {x: sample_image})
        # 显示处理后的图像
        output_image = show_images(fake_img[0], (shape[1], shape[0]))
        print("图片转换完成")
        # 显示和保存处理后的图像
        cv2.imshow("animeGanv2", output_image)
        cv2.imwrite('AE86_Shinkai.jpg', output_image)
        # 等待用户按键后关闭显示窗口
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    # 如果模式为2，通过摄像头实时处理视频流
    elif mode == 2:
        # 打开默认摄像头
        cap = cv2.VideoCapture(0)
        # 记录开始时间用于计算FPS
        start_time = time.time()
        counter = 0
        while True:
            # 从摄像头读取一帧
            ret, frame = cap.read()
            # 处理读取的帧
            sample_image, shape = load_test_data(frame, size=[256, 256])
            # 使用模型进行推断
            fake_img = session.run(None, {x: sample_image})
            # 显示处理后的帧
            output_image = show_images(fake_img[0], (shape[1], shape[0]))
            # 计数器加1
            counter += 1
            # 每秒计算并显示FPS
            if (time.time() - start_time) > 0:
                fps = counter / (time.time() - start_time)
                cv2.putText(output_image, "FPS:{0}".format(float('%.1f' % fps)), (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 1)
                cv2.imshow('animeGanv2', output_image)
            # 如果用户按下'q'键，则退出循环
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        # 释放摄像头资源并关闭所有窗口
        cap.release()
        cv2.destroyAllWindows()
    elif mode == 3:
        # 输入视频路径
        input_video_path = 'kun.mp4'
        # 输出视频路径
        output_video_path = 'kunShinkai_animeGanv2.mp4'
        # 打开视频文件
        cap = cv2.VideoCapture(input_video_path)
        # 检查视频是否成功打开
        if not cap.isOpened():
            print("Error: Could not open video.")
            exit()
        # 读取视频的基本信息
        frame_width = int(cap.get(3))  # 获取视频宽度
        frame_height = int(cap.get(4))  # 获取视频高度
        fps = cap.get(cv2.CAP_PROP_FPS)  # 获取视频帧率
        # 定义视频编码器和创建VideoWriter对象
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # 根据文件扩展名选择正确的编码器
        out = cv2.VideoWriter(output_video_path, fourcc, fps, (frame_width, frame_height))  # 创建视频写入对象
        # 初始化帧数计数器和起始时间
        frame_count = 0
        start_time = time.time()
        while True:
            ret, frame = cap.read()  # 读取一帧视频
            if not ret:
                print("Info: End of video file.")  # 视频结束
                break
            sample_image, shape = load_test_data(frame, size=[256, 256])  # 处理读取的帧
            fake_img = session.run(None, {x: sample_image})  # 使用模型进行推断
            output_image = show_images(fake_img[0], (shape[1], shape[0]))  # 获取输出图像
            # 计算并打印帧速率
            frame_count += 1
            end_time = time.time()
            elapsed_time = end_time - start_time
            if elapsed_time > 0:
                fps = frame_count / elapsed_time
                print(f"FPS: {fps:.2f}")
            out.write(output_image)  # 将处理后的帧写入输出视频
            # 实时显示处理后的视频帧（可选）
            cv2.imshow("Output Video", output_image)
            if cv2.waitKey(1) & 0xFF == ord('q'):  # 按'q'退出
                break
        # 释放资源
        cap.release()
        out.release()
        cv2.destroyAllWindows()
        print(f"视频转换完成: {output_video_path}")
    else:
        print("输入错误，请检查mode的赋值")