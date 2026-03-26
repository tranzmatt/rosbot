"""
headless_sim.launch.py

Launches TurtleBot4 simulation server-only (no GUI process).
Uses gz sim -s directly so there is no Ogre/Qt GUI process to crash.
The GUI can connect remotely from a laptop via: gz sim -g

Set ROSBOT_WORLD_SDF env var to override the world SDF path (e.g. a patched copy).

Spawn order:
  t=5s  clock_bridge      — /clock bridge so controller_manager gets sim time
  t=8s  spawn             — robot + dock entities, description, TF publishers,
                            create3_gz_nodes; intentionally excludes
                            create3_nodes.launch.py to avoid the TB4 diffdrive
                            spawner race (spawner-46 "already loaded" error)
  t=18s bridge            — full ros_gz_bridge (cmd_vel, odom, sensors, …)
  t=24s tb4_nodes         — turtlebot4_nodes (HMI, etc.)
  t=30s diffdrive_spawner — configure + activate diffdrive_controller
"""

import os
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    ExecuteProcess,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node, PushRosNamespace

from irobot_create_common_bringup.namespace import GetNamespacedName
from irobot_create_common_bringup.offset import OffsetParser, RotationalOffsetX, RotationalOffsetY


def generate_launch_description():

    world = LaunchConfiguration("world")
    model = LaunchConfiguration("model")
    namespace = LaunchConfiguration("namespace")
    x = LaunchConfiguration("x")
    y = LaunchConfiguration("y")
    z = LaunchConfiguration("z")
    yaw = LaunchConfiguration("yaw")

    declare_world = DeclareLaunchArgument(
        "world",
        default_value="depot",
        description="Gazebo world name (without .sdf extension)",
    )

    declare_model = DeclareLaunchArgument(
        "model",
        default_value=os.environ.get("TURTLEBOT4_MODEL", "standard"),
        description="TurtleBot4 model: standard or lite",
    )

    declare_namespace = DeclareLaunchArgument(
        "namespace",
        default_value="",
        description="Robot namespace",
    )

    declare_x = DeclareLaunchArgument("x", default_value="0.0", description="Spawn x position")
    declare_y = DeclareLaunchArgument("y", default_value="0.0", description="Spawn y position")
    declare_z = DeclareLaunchArgument("z", default_value="0.0", description="Spawn z position")
    declare_yaw = DeclareLaunchArgument("yaw", default_value="0.0", description="Spawn yaw (radians, 0 = +x)")

    # Allow entrypoint to inject a patched world SDF (e.g. with ogre2 sensors plugin)
    # via environment variable. Falls back to the standard turtlebot4_gz_bringup path.
    world_sdf = os.environ.get("ROSBOT_WORLD_SDF", None)
    if world_sdf is None:
        world_sdf = PathJoinSubstitution([
            FindPackageShare("turtlebot4_gz_bringup"),
            "worlds",
            [world, ".sdf"],
        ])

    # gz sim server only (-s = server, -r = run immediately, no GUI)
    gz_server = ExecuteProcess(
        cmd=["gz", "sim", "-s", "-r", "-v", "3", world_sdf],
        output="screen",
    )

    # Clock bridge: Gazebo /world/<name>/clock → ROS2 /clock
    # Must start before spawn so controller_manager gets sim time.
    clock_bridge = TimerAction(
        period=5.0,
        actions=[
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name="clock_bridge",
                arguments=[["/world/", world, "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"]],
                remappings=[(["/world/", world, "/clock"], "/clock")],
                output="screen",
                parameters=[{"use_sim_time": True}],
            )
        ],
    )

    # Spawn robot and dock into Gazebo, set up descriptions and TF.
    #
    # We expand turtlebot4_spawn.launch.py manually here so we can exclude
    # create3_nodes.launch.py, which contains the TB4's own diffdrive spawner
    # (spawner-46). That spawner races with gz_ros2_control's auto-load and
    # always fails with "already loaded / Failed to configure controller".
    # Our diffdrive_spawner below (at t=30s) handles it cleanly instead.
    robot_name = GetNamespacedName(namespace, "turtlebot4")
    dock_name = GetNamespacedName(namespace, "standard_dock")

    # Dock position: offset from robot by 0.157 m in the direction of yaw
    dock_offset_x = RotationalOffsetX(0.157, yaw)
    dock_offset_y = RotationalOffsetY(0.157, yaw)
    x_dock = OffsetParser(x, dock_offset_x)
    y_dock = OffsetParser(y, dock_offset_y)
    z_robot = OffsetParser(z, -0.0025)   # slightly lower to reduce drop jolt
    yaw_dock = OffsetParser(yaw, 3.1416) # dock faces robot

    spawn = TimerAction(
        period=8.0,
        actions=[
            GroupAction([
                PushRosNamespace(namespace),

                # Robot URDF → robot_state_publisher + joint_state_publisher
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource([
                        PathJoinSubstitution([
                            FindPackageShare("turtlebot4_description"),
                            "launch",
                            "robot_description.launch.py",
                        ])
                    ]),
                    launch_arguments=[
                        ("model", model),
                        ("use_sim_time", "true"),
                    ],
                ),

                # Dock URDF → standard_dock_description topic
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource([
                        PathJoinSubstitution([
                            FindPackageShare("irobot_create_common_bringup"),
                            "launch",
                            "dock_description.launch.py",
                        ])
                    ]),
                    launch_arguments={"gazebo": "ignition"}.items(),
                ),

                # Spawn TurtleBot4 entity into Gazebo
                Node(
                    package="ros_gz_sim",
                    executable="create",
                    arguments=[
                        "-name", robot_name,
                        "-x", x, "-y", y, "-z", z_robot, "-Y", yaw,
                        "-topic", "robot_description",
                    ],
                    output="screen",
                ),

                # Spawn dock entity into Gazebo
                Node(
                    package="ros_gz_sim",
                    executable="create",
                    arguments=[
                        "-name", dock_name,
                        "-x", x_dock, "-y", y_dock, "-z", z, "-Y", yaw_dock,
                        "-topic", "standard_dock_description",
                    ],
                    output="screen",
                ),

                # Create3 Gazebo-side nodes (pose republisher, sensors, buttons)
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource([
                        PathJoinSubstitution([
                            FindPackageShare("irobot_create_gz_bringup"),
                            "launch",
                            "create3_gz_nodes.launch.py",
                        ])
                    ]),
                    launch_arguments=[
                        ("robot_name", robot_name),
                        ("dock_name", dock_name),
                    ],
                ),

                # RPLIDAR link → Gazebo sensor frame static TF
                Node(
                    name="rplidar_stf",
                    package="tf2_ros",
                    executable="static_transform_publisher",
                    output="screen",
                    arguments=[
                        "0", "0", "0", "0", "0", "0.0",
                        "rplidar_link", [robot_name, "/rplidar_link/rplidar"],
                    ],
                    remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
                ),

                # OAKD optical frame → Gazebo camera frame static TF
                Node(
                    name="camera_stf",
                    package="tf2_ros",
                    executable="static_transform_publisher",
                    output="screen",
                    arguments=[
                        "0", "0", "0",
                        "1.5707", "-1.5707", "0",
                        "oakd_rgb_camera_optical_frame",
                        [robot_name, "/oakd_rgb_camera_frame/rgbd_camera"],
                    ],
                    remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
                ),
            ])
        ],
    )

    # ROS-Gazebo bridge (cmd_vel, odom, sensors, etc.)
    bridge = TimerAction(
        period=18.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource([
                    PathJoinSubstitution([
                        FindPackageShare("turtlebot4_gz_bringup"),
                        "launch",
                        "ros_gz_bridge.launch.py",
                    ])
                ]),
                launch_arguments={
                    "model": model,
                    "namespace": namespace,
                }.items(),
            )
        ],
    )

    # TurtleBot4 nodes (HMI etc)
    tb4_nodes = TimerAction(
        period=24.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource([
                    PathJoinSubstitution([
                        FindPackageShare("turtlebot4_gz_bringup"),
                        "launch",
                        "turtlebot4_nodes.launch.py",
                    ])
                ]),
                launch_arguments={
                    "model": model,
                    "namespace": namespace,
                }.items(),
            )
        ],
    )

    # Spawner for diffdrive_controller.
    # TB4's own spawner (from create3_nodes.launch.py) is excluded above to avoid
    # the race condition where it fails with "already loaded / Failed to configure
    # controller" because gz_ros2_control auto-loads the controller first.
    # This spawner runs after the CM has had time to stabilize and succeeds cleanly.
    diffdrive_spawner = TimerAction(
        period=30.0,
        actions=[
            Node(
                package="controller_manager",
                executable="spawner",
                name="diffdrive_spawner",
                arguments=[
                    "diffdrive_controller",
                    "--controller-manager", "/controller_manager",
                    "--controller-manager-timeout", "60",
                ],
                output="screen",
                parameters=[{"use_sim_time": True}],
            )
        ],
    )

    return LaunchDescription([
        declare_world,
        declare_model,
        declare_namespace,
        declare_x,
        declare_y,
        declare_z,
        declare_yaw,
        gz_server,
        clock_bridge,       # t=5s:  /clock bridge
        spawn,              # t=8s:  spawn robot + dock (no create3_nodes spawner)
        bridge,             # t=18s: full ros_gz_bridge
        tb4_nodes,          # t=24s: turtlebot4 nodes
        diffdrive_spawner,  # t=30s: activate diffdrive_controller (sole spawner)
    ])
